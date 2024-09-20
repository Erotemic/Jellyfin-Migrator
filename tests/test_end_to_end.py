def main():
    from jellyfin_migrator.demo.jellyfin_apt_variant import ensure_apt_variant
    from jellyfin_migrator.demo.jellyfin_docker_variant import ensure_docker_variant
    import jellyfin_migrator
    import ubelt as ub

    # Get the path to the jellyfin migrator repo. we are going to copy the
    # entire thing in.
    repo_dpath = ub.Path(jellyfin_migrator.__file__).parent.parent

    # Create two jellyfin servers. One will be the source and one will be the
    # destination.
    apt_variant = ensure_apt_variant()
    docker_variant = ensure_docker_variant()
    print(f'docker_variant.name={docker_variant.name}')
    print(f'apt_variant.name={apt_variant.name}')
    _ = ub.cmd('docker ps', verbose=3)

    # Clear any existing version of the code in the docker container, and
    # copy in a fresh copy of the latest code.
    self = apt_variant
    self.call(['rm', '-rf', 'Jellyfin-Migrator/*'])
    self.copy_into(repo_dpath, '/Jellyfin-Migrator')
    # self.call(['ls', '-al'], cwd='/Jellyfin-Migrator')

    # Delete any previous migration data.
    self.call(['rm', '-rf', '/new'])
    # Run the migrator
    self.call(['python3', '-m', 'jellyfin_migrator'], cwd='/Jellyfin-Migrator')

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

    docker exec -it jellyfin-apiclient-python-test-server bash -c "rm -rf /new && cd /Jellyfin-Migrator && python3 jellyfin_migrator.py"

    # Run the script
    cd /Jellyfin-Migrator
    python3 jellyfin_migrator.py

    python3 Jellyfin-Migrator/jellyfin_id_scanner.py \
            --library-db /config/data/library.db \
            --scan-db /config/data/jellyfin.db
    """

    # Try2
    """
    docker exec -it jellyfin_apt bash
    docker exec -it jellyfin_dockervariant bash

    docker exec -it jellyfin_apt rm -rf Jellyfin-Migrator/* && \
            docker container cp ~/code/Jellyfin-Migrator jellyfin_apt:/

    mkdir -p /jellyfin-dummy
    docker exec -it jellyfin_apt bash -c "rm -rf /new && cd /Jellyfin-Migrator && python3 jellyfin_migrator.py"

    python3 Jellyfin-Migrator/jellyfin_id_scanner.py \
            --library-db /config/data/library.db \
            --scan-db /config/data/jellyfin.db


        ls /var/lib/jellyfin
        ls /var/lib/jellyfin/data
        ls /var/lib/jellyfin/metadata
        ls /var/log/jellyfin
        ls /var/cache/jellyfin/
        ls /etc/jellyfin/
        ls /usr/lib/jellyfin-ffmpeg/ffmpeg
        ls /var/lib/jellyfin/transcodes

        ls ./root/.cache/jellyfin
        ./usr/lib/jellyfin-ffmpeg
        ls ./usr/lib/jellyfin
        ./usr/share/doc/jellyfin-ffmpeg6
        ls ./usr/share/doc/jellyfin
        ./usr/share/doc/jellyfin-web
        ./usr/share/doc/jellyfin-server
        ./usr/share/jellyfin
        ./etc/systemd/system/jellyfin.service.d
        ls ./etc/jellyfin
        ls ./var/lib/jellyfin
        ls ./var/log/jellyfin
        ls ./var/cache/jellyfin
        ls ./jellyfin
    """
