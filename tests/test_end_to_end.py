"""
TODO:
    - [ ] Add collections to source server to test.
"""
import ubelt as ub


def setup_original_container(repo_dpath):
    from jellyfin_migrator.demo.jellyfin_apt_variant import JellyfinAptContainer

    # Create two jellyfin servers. One will be the source and one will be the
    # destination.
    apt_variant = apt_variant = JellyfinAptContainer(mounts=[
        {
            'source': repo_dpath,
            'target': '/Jellyfin-Migrator'
        }
    ])
    apt_variant.reset()
    apt_variant.ensure()
    apt_variant.connect()

    # Clear any existing version of the code in the docker container, and
    # copy in a fresh copy of the latest code.
    apt_variant = apt_variant
    # Check that we can run Python
    apt_variant.start()
    apt_variant.connect()
    apt_variant.call(['python3', '--version'])
    apt_variant.exec('/usr/bin/jellyfin --version', verbose=3, check=False)
    # Run the migrator (with exec for stderr)
    # _ = apt_variant.exec('apt update', verbose=3)
    # _ = apt_variant.exec('apt install python3-pip fd-find tree psmisc sqlite3  --yes', verbose=3)
    # _ = apt_variant.exec('pip install pandas ubelt rich kwutil networkx scriptconfig', verbose=3)

    # TODO: you might need to actually do something in the jellyfin server to
    # get it to populate jellyfin.db, otherwise maybe it is empty and this
    # fails?
    # Create a client to perform some initial configuration.
    from jellyfin_apiclient_python import JellyfinClient
    client = JellyfinClient()
    url = 'http://localhost'
    client.config.app(
        name='DemoServerMediaPopulator',
        version='0.1.0',
        device_name='machine_name',
        device_id='unique_id')
    client.config.data["auth.ssl"] = True
    url = f'{url}:{apt_variant.port}'
    client.auth.connect_to_address(url)
    client.auth.login(url, apt_variant.username, apt_variant.password)

    client.jellyfin.get_users()
    client.jellyfin.get_media_folders()
    client.jellyfin.items()
    client.jellyfin.get_recently_added()

    client.jellyfin.new_user('other-user', 'other-password')

    items = client.jellyfin.search_media_items()['Items']
    # Set two items as a favorite
    for item in items:
        if 'Popeye' in item['Name']:
            client.jellyfin.favorite(item['Id'])
        if 'Clair De Lune' in item['Name']:
            client.jellyfin.favorite(item['Id'])

    # Attempt to play something to create playback.db
    client.jellyfin.new_sync_play_v2('groupname')
    session = client.jellyfin.sessions()[0]
    client.jellyfin.remote_play_media(session['Id'], [item['Id']])

    items = client.jellyfin.search_media_items()['Items']
    # Set two items as a favorite
    for item in items:
        if 'Popeye' in item['Name']:
            client.jellyfin.favorite(item['Id'])
        if 'Clair De Lune' in item['Name']:
            client.jellyfin.favorite(item['Id'])

    # Re-running the server seems to populate jellyfin.db correctly.
    apt_variant.exec('killall /usr/bin/jellyfin')
    apt_variant._run_server()

    # Verify that jellyfin.db has data in it
    _ = apt_variant.exec('du /root/.local/share/jellyfin/data/jellyfin.db', verbose=3)
    _ = apt_variant.exec('ls -al /root/.local/share/jellyfin/data/jellyfin.db', verbose=3)
    _ = apt_variant.exec('ls -al /root/.local/share/jellyfin/data', verbose=3)

    # Delete any previous migration data.
    apt_variant.start()
    apt_variant.connect()
    apt_variant.call(['python3', '--version'])
    return apt_variant


def setup_target_container(repo_dpath, live_local_staging):
    # TODO: ensure media paths have changed
    # sqlite3 library.db "SELECT Path FROM TypedBaseItems;"

    # Now lets try to port
    from jellyfin_migrator.demo.jellyfin_docker_variant import JellyfinDockerContainer
    docker_variant = JellyfinDockerContainer(mounts=[
        {
            # Directly mount the staged data as the new jellyfin configuration.
            'source': live_local_staging,
            'target': '/config',
            'type': 'volume',
        },
        {
            # Also give docker access to this repo for debugging.
            'source': repo_dpath,
            'target': '/Jellyfin-Migrator'
        }
    ])
    try:
        docker_variant.stop()
        docker_variant.remove()
    except Exception:
        ...
    docker_variant.ensure()

    if 0:
        docker_variant.exec('apt update', verbose=3)
        docker_variant.exec('apt install rsync sqlite3 python3 python3-pip --yes', verbose=3)
        docker_variant.exec('python3 -m pip install --break-system-packages pandas ubelt rich kwutil networkx scriptconfig xmltodict', verbose=3)
    else:
        import time
        print("wait a sec, the initial run of jellyfin will need a small bit of time to startup.")
        print("TODO: can we query for when this is done?")
        time.sleep(5)

    # docker_variant.exec('du /config/data/jellyfin.db', verbose=3)
    # docker_variant.exec('sha1sum /config/data/jellyfin.db', verbose=3)
    # docker_variant.exec('sha1sum /config/data/library.db', verbose=3)
    # docker_variant.exec('sqlite3 /config/data/library.db "SELECT Path FROM TypedBaseItems;"', verbose=3)
    # docker_variant.exec('sqlite3 /config/data/jellyfin.db -header -column "SELECT * FROM Users;"', verbose=3)
    return docker_variant


def main():
    """
    An end to end test that will create two docker containers:

        1. An official jellyfin docker container
        2. An ubuntu container with custom jellfin.

    Given these containers we attempt to migrate the ubuntu variant to the
    official docker variant.
    """
    import jellyfin_migrator
    # Get the path to the jellyfin migrator repo. we are going to copy the
    # entire thing in.
    repo_dpath = ub.Path(jellyfin_migrator.__file__).parent.parent
    dpath = ub.Path.appdir('jellyfin-migrator').ensuredir()

    ####
    ####
    ####
    apt_variant = setup_original_container(repo_dpath)

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


def selenium_login(url):
    """
    Logs into a jellyfin server quickly so we can interactively debug.
    """
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    from webdriver_manager.chrome import ChromeDriverManager
    drive_fpath = ChromeDriverManager().install()

    # Set up the Chrome WebDriver
    service = Service(drive_fpath)  # Update this path
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Open Jellyfin web UI
        driver.get(url)

        wait = WebDriverWait(driver, 2)

        # Does not seem to trigger in selenium
        # # Step 1: Check if "Connect to server" screen appears
        # try:
        #     server_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Enter server address']")))
        #     connect_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Connect')]")))
        #     print("Entering server URL and clicking Connect")
        #     server_input.clear()
        #     server_input.send_keys("http://localhost:8097")
        #     connect_button.click()
        # except Exception:
        #     print("Server connection screen not detected, proceeding to login")

        # Step 2: Check if the login screen appears
        try:
            username_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[autocomplete='username']")))
            password_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
            login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.button-submit")))
            print("Entering login credentials")
            username_input.clear()
            username_input.send_keys("jellyfin-user")
            password_input.clear()
            password_input.send_keys("jellyfin-pass")
            login_button.click()
        except Exception:
            print("Login screen not detected")

        # Wait to observe the result
        wait.until(EC.url_contains("home"))

    finally:
        ...
        # input("Press Enter to close the browser...")  # Keep the browser open for review
        # driver.quit()

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
    main()
