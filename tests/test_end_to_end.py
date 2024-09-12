def main():
    # Requires the erotemic branch of git@github.com:Erotemic/jellyfin-apiclient-python.git@erotemic
    # as of 2024-09-12, in the future this may be merged upstream
    # Setup a docker image
    from jellyfin_apiclient_python.demo.demo_jellyfin_server import DemoJellyfinServerManager
    demoman = DemoJellyfinServerManager()
    demoman.ensure_server(reset=1)
    assert demoman.server_exists()

    # For now, lets do things manually
    """
    docker exec -it jellyfin-apiclient-python-test-server bash

    cat /config/data/jellyfin.db
    cat /config/data/library.db

    apt update
    apt install python3 fd-find tree -y

    fdfind ".*.db$"

    python3 -c "
import sqlite3
con = sqlite3.connect('config/data/jellyfin.db')
cur = con.cursor()
res = cur.execute("SELECT * FROM sqlite_master WHERE type='table';")
existing_tables = list(res)
for table in existing_tables:
print(table[0:2])
    "

    docker exec -it jellyfin-apiclient-python-test-server rm -rf Jellyfin-Migrator/* && \
            docker container cp ~/code/Jellyfin-Migrator jellyfin-apiclient-python-test-server:/

    docker exec -it jellyfin-apiclient-python-test-server bash -c "cd /Jellyfin-Migrator && python3 jellyfin_migrator.py"

    # Run the script
    cd /Jellyfin-Migrator
    python3 jellyfin_migrator.py

    python3 Jellyfin-Migrator/jellyfin_id_scanner.py \
            --library-db /config/data/library.db \
            --scan-db /config/data/jellyfin.db
    """
