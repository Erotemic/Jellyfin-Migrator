"""
TODO:
    - [ ] Add collections to source server to test.
"""


def test_end_to_end():
    """
    An end to end test that will create two docker containers:

        1. An official jellyfin docker container
        2. An ubuntu container with custom jellfin.

    Given these containers we attempt to migrate the ubuntu variant to the
    official docker variant.
    """
    import ubelt as ub
    from jellyfin_migrator.demo.migration_test_setups import setup_original_container
    from jellyfin_migrator.demo.migration_test_setups import setup_target_container
    from jellyfin_migrator.demo.migration_test_setups import selenium_login
    dpath = ub.Path.appdir('jellyfin-migrator').ensuredir()

    ####
    ####
    ####
    apt_variant = setup_original_container()

    USER_INTERACTIVE = 0
    if USER_INTERACTIVE:
        selenium_login("http://localhost:8098/")

    ####
    ####
    ####
    # RUN MIGRATION
    config_fpath = dpath / 'apt_to_docker_config.yaml'
    config_fpath.write_text(ub.codeblock(
        '''
        source: root-apt
        target: docker
        original: root-apt

        staging_root: /staging-e2e
        log_file: /staging-e2e/jf-migrator-e2e.log

        media_replacements:
            - src: /data/jellyfin/media
              dst: /media
        '''))

    apt_variant.call(['rm', '-rf', '/staging-e2e'])
    apt_variant.call(['mkdir', '-p', '/staging-e2e'])
    apt_variant.copy_into(config_fpath, ub.Path('/staging-e2e/apt_to_docker_config.yaml'))
    _ = apt_variant.exec(
        'python3 -m jellyfin_migrator --config /staging-e2e/apt_to_docker_config.yaml',
        cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')

    _ = apt_variant.exec('ls', cwd='/staging-e2e', verbose=3)
    # Check that the paths look like they updated correctly.
    # _ = apt_variant.exec('sqlite3 /root/.local/share/jellyfin/data/library.db "SELECT Path FROM TypedBaseItems;"', verbose=3)
    _ = apt_variant.exec('sqlite3 /staging-e2e/data/library.db "SELECT Path FROM TypedBaseItems;"', verbose=3)

    # Create two variants of the staging directory for debugging
    raw_local_staging = (dpath / 'staging-raw')
    live_local_staging = (dpath / 'staging-live')
    try:
        raw_local_staging.delete()
        live_local_staging.delete()
    except PermissionError:
        ub.cmd(f'sudo rm -rf {raw_local_staging}', verbose=3, system=True)
        ub.cmd(f'sudo rm -rf {live_local_staging}', verbose=3, system=True)
    apt_variant.copy_out('staging-e2e', to_path=raw_local_staging)
    raw_local_staging.copy(live_local_staging)

    if 1:
        from jellyfin_migrator.debug_tools import check_main_databases
        check_main_databases(raw_local_staging)
        check_main_databases(raw_local_staging, include='TypedBaseItems')

        hashes1 = {p.relative_to(raw_local_staging): ub.hash_file(p) for p in sorted(raw_local_staging.glob('**')) if p.is_file()}
        hashes2 = {p.relative_to(live_local_staging): ub.hash_file(p) for p in sorted(live_local_staging.glob('**')) if p.is_file()}
        difference = ub.IndexableWalker(hashes1).diff(hashes2)
        assert difference['similarity'] == 1

    ####
    ####
    ####
    docker_variant = setup_target_container(live_local_staging)

    # Create a client to perform some initial configuration.
    port = docker_variant.port
    username = apt_variant.username
    password = apt_variant.password
    from jellyfin_apiclient_python import JellyfinClient
    client = JellyfinClient()
    url = 'http://localhost'
    client.config.app(
        name='DemoServerChecker',
        version='0.1.0',
        device_name='machine_name',
        device_id='unique_id')
    client.config.data["auth.ssl"] = True
    url = f'{url}:{port}'
    client.auth.connect_to_address(url)
    client.auth.login(url, username, password)
    items = client.jellyfin.search_media_items()['Items']

    item_id = client.jellyfin.search_media_items('Great Train')['Items'][0]['Id']
    item_path = client.jellyfin.get_item(item_id=item_id)['Path']
    assert not item_path.startswith('/data/jellyfin/media/movies/'), 'should have moved'

    print(f'items = {ub.urepr(items, nl=2)}')
    from collections import Counter
    item_type_hist = Counter([item['Type'] for item in items])
    assert item_type_hist == {
        'Audio': 3,
        'Folder': 3,
        'Movie': 2,
        'BoxSet': 2
    }
    for item in items:
        if 'Popeye' in item['Name']:
            assert item['UserData']['IsFavorite']
        elif 'Clair De Lune' in item['Name']:
            assert item['UserData']['IsFavorite']
        else:
            assert not item['UserData']['IsFavorite']

    USER_INTERACTIVE = 0
    if USER_INTERACTIVE:
        selenium_login("http://localhost:8097/")

    if 0:
        hashes1 = {p.relative_to(raw_local_staging): ub.hash_file(p) for p in sorted(raw_local_staging.glob('**')) if p.is_file()}
        hashes2 = {p.relative_to(live_local_staging): ub.hash_file(p) for p in sorted(live_local_staging.glob('**')) if p.is_file()}
        difference = ub.IndexableWalker(hashes1).diff(hashes2)
        print(f'difference = {ub.urepr(difference, nl=-1)}')

        # Force the database to update itself
        # sqlite3 /config/data/library.db "PRAGMA wal_checkpoint(FULL);"
        # sqlite3 /config/data/jellyfin.db "PRAGMA wal_checkpoint(FULL);"

        # import xdev
        # old = (raw_local_staging / 'config/encoding.xml').read_text()
        # new = (live_local_staging / 'config/encoding.xml').read_text()
        # print(xdev.difftext(old, new, colored=True))

        # check_main_databases(raw_local_staging )
        # check_main_databases(live_local_staging )

        # _ = apt_variant.exec(ub.codeblock(
        #     r'''
        #     python3 -m jellyfin_migrator.id_scanner \
        #         --library-db /config/data/library.db \
        #         --scan-db /config/data/library.db
        #     '''), cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')

        _ = docker_variant.exec(ub.codeblock(
            r'''
            sqlite3 /config/data/library.db "PRAGMA wal_checkpoint(FULL);"
            '''), cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')
        _ = docker_variant.exec(ub.codeblock(
            r'''
            python3 -m jellyfin_migrator.debug_tools /config
            '''), cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')

        # print(f'docker_variant.name={docker_variant.name}')
        # docker_variant.exec('rm -rf /staging')
        # docker_variant.copy_into(local_staging, '/staging')
        # docker_variant.exec('ls /', verbose=3)
        # docker_variant.exec('chmod +x /staging/accept.sh', verbose=3)
        # docker_variant.exec('cat /staging/accept.sh', verbose=3)
        # docker_variant.exec('sha1sum /staging/data/jellyfin.db', verbose=3)
        # docker_variant.exec('sha1sum /config/data/jellyfin.db', verbose=3)
        # docker_variant.exec('ls -al /staging/data/jellyfin.db', verbose=3)
        # docker_variant.exec('ls -al /config/data/jellyfin.db', verbose=3)
        # docker_variant.exec('sqlite3 /', verbose=3)

        # TODO:
        # Ensure that we are expecting media to live in /media in the docker
        # container instead of /data/jellyfin/media, which is where it lives
        # outside of the docker container.

        # docker_variant.exec('./accept.sh', cwd='/staging', verbose=3)
        # print(f'apt_variant.name={apt_variant.name}')

        # Ok, this isn't working why?
        # We can't login. Are we not copying the user credentials over?
        # Let's check that first.

        from jellyfin_migrator.debug_tools import check_main_databases
        check_main_databases(raw_local_staging, include='TypedBaseItems')

        check_main_databases(live_local_staging, include='TypedBaseItems')

        apt_variant.exec(ub.codeblock(
            r'''
            python3 -m jellyfin_migrator.debug_tools /root/.local/share/jellyfin --include TypedBaseItems
            '''), cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')

NOTES = r"""


See:
    ~/code/Jellyfin-Migrator/tests/notes.txt

    It looks like the update to the guid of /config/root gets reverted

"""

if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/tests/test_end_to_end.py
    """
    test_end_to_end()
