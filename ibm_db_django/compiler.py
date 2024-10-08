# +--------------------------------------------------------------------------+
# |  Licensed Materials - Property of IBM                                    |
# |                                                                          |
# | (C) Copyright IBM Corporation 2009-2020.                                      |
# +--------------------------------------------------------------------------+
# | This module complies with Django 1.0 and is                              |
# | Licensed under the Apache License, Version 2.0 (the "License");          |
# | you may not use this file except in compliance with the License.         |
# | You may obtain a copy of the License at                                  |
# | http://www.apache.org/licenses/LICENSE-2.0 Unless required by applicable |
# | law or agreed to in writing, software distributed under the License is   |
# | distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY |
# | KIND, either express or implied. See the License for the specific        |
# | language governing permissions and limitations under the License.        |
# +--------------------------------------------------------------------------+
# | Authors: Ambrish Bhargava, Tarun Pasrija, Rahul Priyadarshi              |
# +--------------------------------------------------------------------------+

from django.db.models.sql import compiler
import sys

if sys.version_info >= (3, ):
    try:
        from itertools import zip_longest
    except ImportError:
        from itertools import zip_longest as zip_longest
# For checking django's version
from django import VERSION as djangoVersion

import datetime
from django.db.models.sql.query import get_order_dir
from django.db.models.sql.constants import ORDER_DIR
from django.db.models.expressions import OrderBy, Random, RawSQL, Ref
from django.utils.hashable import make_hashable
from django.db.utils import DatabaseError
FORCE = object()

class SQLCompiler( compiler.SQLCompiler ):
    def compile_order_by(self, node, select_format=False):
        template = None
        if node.nulls_last:
            template = '%(expression)s IS NULL, %(expression)s %(ordering)s'
        elif node.nulls_first:
            template = '%(expression)s IS NOT NULL, %(expression)s %(ordering)s'

        sql, params = node.as_sql(self, self.connection, template=template)
        if select_format is FORCE or (select_format and not self.query.subquery):
            return node.output_field.select_format(self, sql, params)
        return sql, params

    def get_order_by(self):
        """
        Return a list of 2-tuples of form (expr, (sql, params, is_ref)) for the
        ORDER BY clause.

        The order_by clause can alter the select clause (for example it
        can add aliases to clauses that do not yet have one, or it can
        add totally new select clauses).
        """
        if self.query.extra_order_by:
            ordering = self.query.extra_order_by
        elif not self.query.default_ordering:
            ordering = self.query.order_by
        elif self.query.order_by:
            ordering = self.query.order_by
        elif self.query.get_meta().ordering:
            ordering = self.query.get_meta().ordering
            self._meta_ordering = ordering
        else:
            ordering = []
        if self.query.standard_ordering:
            asc, desc = ORDER_DIR['ASC']
        else:
            asc, desc = ORDER_DIR['DESC']

        order_by = []
        for field in ordering:
            if hasattr(field, 'resolve_expression'):
                if not isinstance(field, OrderBy):
                    field = field.asc()
                if not self.query.standard_ordering:
                    field.reverse_ordering()
                    order_by.append((field, True))
                else:
                    order_by.append((field, False))
                continue
            if field == '?':  # random
                order_by.append((OrderBy(Random()), False))
                continue

            col, order = get_order_dir(field, asc)
            descending = order == 'DESC'

            if col in self.query.annotation_select:
                # Reference to expression in SELECT clause
                order_by.append((
                    OrderBy(Ref(col, self.query.annotation_select[col]), descending=descending),
                    True))
                continue
            if col in self.query.annotations:
                # References to an expression which is masked out of the SELECT clause
                order_by.append((
                    OrderBy(self.query.annotations[col], descending=descending),
                    False))
                continue

            if '.' in field:
                # This came in through an extra(order_by=...) addition. Pass it
                # on verbatim.
                table, col = col.split('.', 1)
                order_by.append((
                    OrderBy(
                        RawSQL('%s.%s' % (self.quote_name_unless_alias(table), col), []),
                        descending=descending
                    ), False))
                continue

            if not self.query._extra or col not in self.query._extra:
                # 'col' is of the form 'field' or 'field1__field2' or
                # '-field1__field2__field', etc.
                order_by.extend(self.find_ordering_name(
                    field, self.query.get_meta(), default_order=asc))
            else:
                if col not in self.query.extra_select:
                    order_by.append((
                        OrderBy(RawSQL(*self.query.extra[col]), descending=descending),
                        False))
                else:
                    order_by.append((
                        OrderBy(Ref(col, RawSQL(*self.query.extra[col])), descending=descending),
                        True))
        result = []
        seen = set()

        for expr, is_ref in order_by:
            resolved = expr.resolve_expression(self.query, allow_joins=True, reuse=None)
            if self.query.combinator:
                src = resolved.get_source_expressions()[0]
                # Relabel order by columns to raw numbers if this is a combined
                # query; necessary since the columns can't be referenced by the
                # fully qualified name and the simple column names may collide.
                for idx, (sel_expr, _, col_alias) in enumerate(self.select):
                    if is_ref and col_alias == src.refs:
                        src = src.source
                    elif col_alias:
                        continue
                    if src == sel_expr:
                        resolved.set_source_expressions([RawSQL('%d' % (idx + 1), ())])
                        break
                else:
                    raise DatabaseError('ORDER BY term does not match any column in the result set.')
            sql, params = self.compile_order_by(resolved)
            # Don't add the same column twice, but the order direction is
            # not taken into account so we strip it. When this entire method
            # is refactored into expressions, then we can check each part as we
            # generate it.
            without_ordering = self.ordering_parts.search(sql).group(1)
            params_hash = make_hashable(params)
            if (without_ordering, params_hash) in seen:
                continue
            seen.add((without_ordering, params_hash))
            result.append((resolved, (sql, params, is_ref)))
        return result

    def pre_sql_setup(self):
        """
        Do any necessary class setup immediately prior to producing SQL. This
        is for things that can't necessarily be done in __init__ because we
        might not have all the pieces in place at that time.
        """
        extra_select, order_by, group_by = super().pre_sql_setup()

        if group_by:
            group_by_list = []
            for (sql, params) in group_by:
                group_by_list.append([sql, params])

            group_by = []
            found_positional_param = False
            for (sql, params) in group_by_list:
                if (sql.count("%s") > 0) and params:

                    for parm in params:
                        if(isinstance(parm, memoryview)):
                            replace_string = "BX\'%s\'" % parm.obj.hex()
                        else:
                            replace_string = parm

                        if((isinstance(parm, str) and
                           (parm.find('DATE') == -1) and
                           (parm.find('TIMESTAMP') == -1)) or
                            (isinstance(parm, datetime.date))):
                            replace_string = "'%s'" % replace_string
                        else:
                            replace_string = str(replace_string)

                        sql = sql.replace("%s", replace_string, 1)

                    #sql = sql % tuple(params)
                    params = []
                    found_positional_param = True
                group_by.append((sql, params))

            if found_positional_param:
                self.select = self.get_updated_select(self.select)

        return extra_select, order_by, group_by

    def get_updated_select(self, select):
        """
        Return three values:
        - a list of 3-tuples of (expression, (sql, params), alias)

        The (sql, params) is what the expression will produce, and alias is the
        "AS alias" for the column (possibly None).
        """

        ret = []
        for col, (sql, params), alias in select:
            #Db2 doesnt accept positional parameters in Group By clause.
            if (sql.count("%s") > 0) and params:

                for parm in params:
                    if(isinstance(parm, memoryview)):
                        replace_string = "BX\'%s\'" % parm.obj.hex()
                    else:
                        replace_string = parm

                    if((isinstance(parm, str) and
                       (parm.find('DATE') == -1) and
                       (parm.find('TIMESTAMP') == -1)) or
                        (isinstance(parm, datetime.date))):
                        replace_string = "'%s'" % replace_string
                    else:
                        replace_string = str(replace_string)
                    sql = sql.replace("%s", replace_string, 1)

                params = []
            ret.append((col, (sql, params), alias))
        return ret
    
    def __map23(self, value, field):
        if sys.version_info >= (3, ):
            return zip_longest(value, field)
        else:
            return map(None, value, field)
        
    #This function  convert 0/1 to boolean type for BooleanField/NullBooleanField
    def resolve_columns( self, row, fields = () ):
        values = []
        index_extra_select = len( list(self.query.extra_select.keys()) )
        for value, field in self.__map23( row[index_extra_select:], fields ):
            if ( field and field.get_internal_type() in ( "BooleanField", "NullBooleanField" ) and value in ( 0, 1 ) ):
                value = bool( value )
            values.append( value )
        return row[:index_extra_select] + tuple( values )
    
    # For case insensitive search, converting parameter value to upper case.
    # The right hand side will get converted to upper case in the SQL itself.
    def __do_filter( self, children ):
        for index in range( len( children ) ):
            if not isinstance( children[index], ( tuple, list ) ):
                if hasattr( children[index], 'children' ):
                    self.__do_filter( children[index].children )
            elif isinstance( children[index], tuple ):
                node = list( children[index] )
                if node[1].find( "iexact" ) != -1 or \
                    node[1].find( "icontains" ) != -1 or \
                    node[1].find( "istartswith" ) != -1 or \
                    node[1].find( "iendswith" ) != -1:
                    if node[2] == True:
                        node[3] = node[3].upper()
                        children[index] = tuple( node )

class SQLInsertCompiler( compiler.SQLInsertCompiler, SQLCompiler ):
    pass

class SQLDeleteCompiler( compiler.SQLDeleteCompiler, SQLCompiler ):
    pass

class SQLUpdateCompiler( compiler.SQLUpdateCompiler, SQLCompiler ):
    pass

class SQLAggregateCompiler( compiler.SQLAggregateCompiler, SQLCompiler ):
    pass

if djangoVersion[0:2] < ( 1, 8 ):
    class SQLDateCompiler(compiler.SQLDateCompiler, SQLCompiler):
        pass

if djangoVersion[0:2] >= ( 1, 6 ) and djangoVersion[0:2] < ( 1, 8 ):
    class SQLDateTimeCompiler(compiler.SQLDateTimeCompiler, SQLCompiler):
        pass
