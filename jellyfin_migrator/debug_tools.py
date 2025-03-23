import sqlite3
import kwutil
import ubelt as ub
import pandas as pd
import rich


def check_staging_data(staging_dpath):
    """
    Perform a check on staged data to verify that paths are updated correctly.

    Ignore:
        staging_dpath = ub.Path('~/.cache/jellyfin-migrator/staging').expand()

    Ignore:
        /staging/staged-data/data/library.db
        sqlite3 /staging/staged-data/data/library.db "SELECT Path FROM TypedBaseItems

    """
    jellyfin_db_fpath = (staging_dpath / 'staged-data/data/jellyfin.db')
    library_db_fpath = (staging_dpath / 'staged-data/data/library.db')

    database_fpath = jellyfin_db_fpath
    jellyfin_tables = report_sqlite_database(database_fpath)  # NOQA

    database_fpath = library_db_fpath
    library_tables = report_sqlite_database(database_fpath)  # NOQA

    # user_table = tables['Users']
    # rich.print(user_table.T.to_string())

    system_xml_data = kwutil.XML.load(staging_dpath / 'staged-data/config/system.xml')
    print(f'system_xml_data = {ub.urepr(system_xml_data, nl=3)}')

    mblink_files = list((staging_dpath / 'staged-data/root').glob('**/*.mblink'))
    mblink_xml_files = list((staging_dpath / 'staged-data/root').glob('**/*.xml'))

    from rich.syntax import Syntax
    from rich.panel import Panel
    for fpath in mblink_files:
        rich.print(Panel(fpath.read_text(), title=str(fpath)))

    for fpath in mblink_xml_files:
        rich.print(Panel(Syntax(fpath.read_text(), 'xml'), title=str(fpath)))


def report_sqlite_database(database_fpath):
    from rich.markup import escape
    con = sqlite3.connect(database_fpath)

    # List all tables in the database
    table_names = list(pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", con)['name'])
    rich.print(f'[white]=== REPORT FOR: {database_fpath} - {len(table_names)}')

    tables = {}
    for idx, table_name in enumerate(table_names, start=1):
        table = pd.read_sql_query(f"SELECT * FROM {table_name}", con)
        tables[table_name] = table

    for idx, (table_name, table) in enumerate(tables.items()):
        column_names = table.columns.values.tolist()
        rich.print(f' - tablename: {table_name}')
        rich.print(f'   nRows: {len(table)}')
        rich.print(f'   nCols: {len(table.columns)}')

    for idx, (table_name, table) in enumerate(tables.items()):
        column_names = table.columns.values.tolist()
        rich.print(f' - tablename: {table_name}')
        rich.print(f'   nRows: {len(table)}')
        rich.print(f'   nCols: {len(table.columns)}')
        rich.print(ub.indent(f'columns = {ub.urepr(column_names, nl=1)}', '   '))
        ...

    for idx, (table_name, table) in enumerate(tables.items()):
        do_transpose = len(str(table.columns)) > 200
        rich.print(f'[white]--- {database_fpath} {idx} / {len(table_names)}')
        rich.print(f'[white]--- TABLE: {table_name} ---')
        if do_transpose:
            rich.print('[white]--- TRANSPOSED')
            if len(table) > 3:
                rich.print('[white]--- TRUNCATED')
                text = table.T.to_string(max_cols=5)
            else:
                text = table.T.to_string()
        else:
            text = table.to_string()

        rich.print(f'[white]--- nRows={table.shape[0]}')
        rich.print(f'[white]--- nCols={table.shape[1]}')
        rich.print(f'[white]--- {ub.urepr(table.columns, nl=0)}')
        rich.print(escape(text))

        if table_name == 'TypedBaseItems':
            print('Hack to show all paths:')
            print(table['Path'])

    return tables
