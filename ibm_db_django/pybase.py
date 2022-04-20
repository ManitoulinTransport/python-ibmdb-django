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
#from builtins import True
from _ast import Or

from . import Database

from decimal import Decimal
import regex

import datetime
# For checking django's version
from django import VERSION as djangoVersion

if ( djangoVersion[0:2] > ( 1, 1 ) ):
    from django.db import utils
    import sys
if ( djangoVersion[0:2] >= ( 1, 4) ):
    from django.utils import timezone
    from django.conf import settings
    import warnings
if ( djangoVersion[0:2] >= ( 1, 5 )):
    from django.utils.encoding import force_bytes, force_text
    from django.utils import six
    import re
 
_IS_JYTHON = sys.platform.startswith( 'java' )
if _IS_JYTHON:
    dbms_name = 'dbname'
else:
    dbms_name = 'dbms_name'

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError
if ( djangoVersion[0:2] >= ( 1, 6 )):
    Error = Database.Error
    InterfaceError = Database.InterfaceError
    DataError = Database.DataError
    OperationalError = Database.OperationalError
    InternalError = Database.InternalError
    ProgrammingError = Database.ProgrammingError
    NotSupportedError = Database.NotSupportedError
    
class DatabaseWrapper( object ):
    # Get new database connection for non persistance connection 
    def get_new_connection(self, kwargs):
        SchemaFlag= False
        scrollable_cursor = False

        kwargsKeys = list(kwargs.keys())
        if ( kwargsKeys.__contains__( 'port' ) and 
            kwargsKeys.__contains__( 'host' ) ):
            kwargs['dsn'] = "DATABASE=%s;HOSTNAME=%s;PORT=%s;PROTOCOL=TCPIP;" % ( 
                     kwargs.get( 'database' ),
                     kwargs.get( 'host' ),
                     kwargs.get( 'port' )
            )
        else:
            kwargs['dsn'] = kwargs.get( 'database' )

        if ( kwargsKeys.__contains__( 'currentschema' )):
            kwargs['dsn'] += "CurrentSchema=%s;" % (  kwargs.get( 'currentschema' ))
            del kwargs['currentschema']

        if ( kwargsKeys.__contains__( 'security' )):
            kwargs['dsn'] += "security=%s;" % (  kwargs.get( 'security' ))
            del kwargs['security']

        if ( kwargsKeys.__contains__( 'sslclientkeystoredb' )):
            kwargs['dsn'] += "SSLCLIENTKEYSTOREDB=%s;" % (  kwargs.get( 'sslclientkeystoredb' ))
            del kwargs['sslclientkeystoredb']

        if ( kwargsKeys.__contains__( 'sslclientkeystoredbpassword' )):
            kwargs['dsn'] += "SSLCLIENTKEYSTOREDBPASSWORD=%s;" % (  kwargs.get( 'sslclientkeystoredbpassword' ))
            del kwargs['sslclientkeystoredbpassword']

        if ( kwargsKeys.__contains__( 'sslclientkeystash' )):
            kwargs['dsn'] += "SSLCLIENTKEYSTASH=%s;" % (  kwargs.get( 'sslclientkeystash' ))
            del kwargs['sslclientkeystash']

        if ( kwargsKeys.__contains__( 'sslservercertificate' )):
            kwargs['dsn'] += "SSLSERVERCERTIFICATE=%s;" % (  kwargs.get( 'sslservercertificate' ))
            del kwargs['sslservercertificate']

        conn_options = {'autocommit': False}
        kwargs['conn_options'] = conn_options
        if 'options' in kwargs:
            kwargs.update(kwargs.get('options'))
            del kwargs['options']

        if kwargsKeys.__contains__( 'port' ):
            del kwargs['port']
        
        pconnect_flag = False
        if kwargsKeys.__contains__( 'PCONNECT' ):
            pconnect_flag = kwargs['PCONNECT']
            del kwargs['PCONNECT']
            
        if pconnect_flag:
            connection = Database.pconnect( **kwargs )
        else:
            connection = Database.connect( **kwargs )
        connection.autocommit = connection.set_autocommit

        if SchemaFlag:
            schema = connection.set_current_schema(currentschema)

        return connection
    
    def is_active( self, connection = None ):
        return bool(connection.cursor())
        
    # Over-riding _cursor method to return DB2 cursor.
    def _cursor( self, connection ):
        return DB2CursorWrapper( connection )
                    
    def close( self, connection ):
        connection.close()
        
    def get_server_version( self, connection ):
        self.connection = connection
        if not self.connection:
            self.cursor()
        return tuple( int( version ) for version in self.connection.server_info()[1].split( "." ) )
    
class DB2CursorWrapper():
        
    """
    This is the wrapper around IBM_DB_DBI in order to support format parameter style
    IBM_DB_DBI supports qmark, where as Django support format style, 
    hence this conversion is required. 

    pyodbc.Cursor cannot be subclassed, so we store it as an attribute
    """

    def __init__(self, connection):
        self.cursor: Database.Cursor = connection.cursor()

    def __iter__(self):
        return self.cursor

    def __getattr__(self, attr):
        return getattr(self.cursor, attr)

    def get_current_schema(self):
        self.execute('select CURRENT_SCHEMA from sysibm.sysdummy1')
        return self.fetchone()[0]

    def set_current_schema(self, schema):
        self.execute(f'SET CURRENT_SCHEMA = {schema}')

    def close(self):
        """
        Django calls close() twice on some cursors, but pyodbc does not allow this.
        pyodbc deletes the 'connection' attribute when closing a cursor, so we check for that.

        In the unlikely event that this code prevents close() from being called, pyodbc will close
        the cursor automatically when it goes out of scope.
        """
        if getattr(self, 'connection', False):
            self.cursor.close()

    def execute(self, query, params=()):
        if params:
            query = self.convert_query(query)
        result = self._wrap_execute(partial(self.cursor.execute, query, params))
        return result

    def executemany(self, query, param_list):
        if not param_list:
            # empty param_list means do nothing (execute the query zero times)
            return
        query = self.convert_query(query)
        result = self._wrap_execute(partial(self.cursor.executemany, query, param_list))
        return result

    def _wrap_execute(self, execute):
        try:
            result = execute()
        except Database.Error as e:
            # iaccess seems to be sending incorrect sqlstate for some errors
            # reraise "referential constraint violation" errors as IntegrityError
            if e.args[0] == 'HY000' and SQLCODE_0530_REGEX.match(e.args[1]):
                raise utils.IntegrityError(*e.args, execute.func, *execute.args)
            elif e.args[0] == 'HY000' and SQLCODE_0910_REGEX.match(e.args[1]):
                # file in use error (likely in the same transaction)
                query, _params, *_ = execute.args
                if query.startswith('ALTER TABLE') and 'RESTART WITH' in query:
                    raise utils.ProgrammingError(
                        *e.args,
                        execute.func,
                        execute.args,
                        "Db2 for iSeries cannot reset a table's primary key sequence during same "
                        "transaction as insert/update on that table"
                    )
            raise type(e)(*e.args, execute.func, execute.args)
        if result == self.cursor:
            return self
        return result

    def convert_query(self, query):
        """
        Django uses "format" style placeholders, but the iaccess odbc driver uses "qmark" style.
        This fixes it -- but note that if you want to use a literal "%s" in a query,
        you'll need to use "%%s".
        """
        return FORMAT_QMARK_REGEX.sub('?', query).replace('%%', '%')

    def _row_factory(self, row: Optional[Database.Row]):
        if row is None:
            return row
        return tuple(row)

    def fetchone(self):
        return self._row_factory(self.cursor.fetchone())

    def fetchmany(self, size):
        return [self._row_factory(row) for row in self.cursor.fetchmany(size)]

    def fetchall(self):
        return [self._row_factory(row) for row in self.cursor.fetchall()]

    @property
    def last_identity_val(self):
        result = self.execute('SELECT IDENTITY_VAL_LOCAL() AS IDENTITY FROM SYSIBM.SYSDUMMY1')
        row = result.fetchone()
        return row[0]

    def quote_value(self, value):
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time, str)):
            return f"'{value}'"
        if isinstance(value, bool):
            return '1' if value else '0'
        return str(value)

