# +--------------------------------------------------------------------------+
# |  Licensed Materials - Property of IBM                                    |
# |                                                                          |
# | (C) Copyright IBM Corporation 2009-2018.                                      |
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

"""
Custom Query class for DB2.
Derives from: django.db.models.sql.query.Query
"""


def query_class(QueryClass):
    class DB2QueryClass(QueryClass):
        # http://www.python.org/dev/peps/pep-0307/
        # See Extended __reduce__ API
        def __reduce__(self):
            return (__newobj__, (QueryClass,))

        # For case insensitive search, converting parameter value to upper case.
        # The right hand side will get converted to upper case in the SQL itself.
        from django.db.models.sql.where import AND
        def add_filter(self, filter_expr, connector=AND, negate=False, trim=False,
                       can_reuse=None, process_extras=True):
            if len(filter_expr) != 0 and filter_expr is not None:
                filter_expr = list(filter_expr)
                if filter_expr[0].find("__iendswith") != -1 or \
                        filter_expr[0].find("__istartswith") != -1 or \
                        filter_expr[0].find("__icontains") != -1 or \
                        filter_expr[0].find("__iexact") != -1:
                    filter_expr[1] = filter_expr[1].upper()

                filter_expr = tuple(filter_expr)
            return super(DB2QueryClass, self).add_filter(filter_expr, connector,
                                                         negate, trim, can_reuse, process_extras)

    return DB2QueryClass


# Method to make DB2QueryClass picklable
def __newobj__(QueryClass):
    # http://www.python.org/dev/peps/pep-0307/
    # The __newobj__ unpickling function
    DB2QueryClass = query_class(QueryClass)
    return DB2QueryClass.__new__(DB2QueryClass)
