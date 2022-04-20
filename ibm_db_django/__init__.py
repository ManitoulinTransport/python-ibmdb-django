__version__ = "1.3.0.0"


try:
    import pyodbc as Database
except:
    Database = None
else:
    pyodbc_version = tuple(int(x) for x in Database.version.split('.'))
    if pyodbc_version < (4, 0, 0):
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(f'PyODBC 4.0 or later required; you have {pyodbc_version}.')
