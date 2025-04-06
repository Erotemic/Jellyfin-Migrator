"""
This test checks that we can run a migration outside of the live instance.
"""
import ubelt as ub
from jellyfin_migrator.demo.migration_test_setups import setup_original_container
from jellyfin_migrator.demo.migration_test_setups import setup_target_container
from jellyfin_migrator.demo.migration_test_setups import selenium_login


def test_out_of_source_migration():
    import jellyfin_migrator
    # Get the path to the jellyfin migrator repo. we are going to copy the
    # entire thing in.
    repo_dpath = ub.Path(jellyfin_migrator.__file__).parent.parent
    dpath = ub.Path.appdir('jellyfin-migrator/tests/oos').ensuredir()

    ####
    ####
    ####
    apt_variant = setup_original_container(repo_dpath)

    USER_INTERACTIVE = 0
    if USER_INTERACTIVE:
        selenium_login("http://localhost:8098/")

    local_source = (dpath / 'local-source').ensuredir()
    apt_variant.copy_out('/root/.local/share/jellyfin', to_path=local_source / 'data')
    apt_variant.copy_out('/root/.cache/jellyfin', to_path=local_source / 'cache')
    apt_variant.copy_out('/root/.config/jellyfin', to_path=local_source / 'config')
    apt_variant.copy_out('/usr/lib/jellyfin-ffmpeg', to_path=local_source / 'ffmpeg')

    local_staging = (dpath / 'local-staging').ensuredir()

    ub.cmd('sudo chmod o+r -R .', cwd=local_staging)

    ####
    ####
    ####
    # RUN MIGRATION
    config_fpath = dpath / 'apt_to_docker_config.yaml'
    config_fpath.write_text(ub.codeblock(
        f'''
        source:
            config:     {local_source}/config
            cache:      {local_source}/cache
            log:        {local_source}/data/log
            data:       {local_source}/data
            transcodes: {local_source}/cache/transcodes
            ffmpeg:     {local_source}/ffmpeg/ffmpeg

        target: docker

        original:
            config:     /root/.config/jellyfin
            cache:      /root/.cache/jellyfin
            log:        /root/.local/share/jellyfin/log
            data:       /root/.local/share/jellyfin
            transcodes: /root/.cache/jellyfin/transcodes
            ffmpeg:     /usr/lib/jellyfin-ffmpeg/ffmpeg

        staging_root: {local_staging}
        log_file: {local_staging}/jf-migrator-e2e.log

        media_replacements:
            - src: /data/jellyfin/media
              dst: /media
        '''))

    from jellyfin_migrator import core
    core.main(argv=['--config', str(config_fpath)], thread_logs=False)

    # Run the migrator code in our local environment

    ub.cmd('python3 -m jellyfin_migrator --config /staging-e2e/apt_to_docker_config.yaml',
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
    docker_variant = setup_target_container(repo_dpath, live_local_staging)

    # Create a client to perform some initial configuration.
    port = docker_variant.port
    username = 'jellyfin-user'
    password = 'jellyfin-pass'
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
    print(f'items = {ub.urepr(items, nl=2)}')
    assert len(items) == 7
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


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/tests/test_out_of_source_migration.py
    """
    import xdoctest
    xdoctest.doctest_module(__file__)
