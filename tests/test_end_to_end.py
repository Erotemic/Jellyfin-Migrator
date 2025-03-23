def main():
    """
    An end to end test that will create two docker containers:

        1. An official jellyfin docker container
        2. An ubuntu container with custom jellfin.

    Given these containers we attempt to migrate the ubuntu variant to the
    official docker variant.
    """
    from jellyfin_migrator.demo.jellyfin_apt_variant import JellyfinAptContainer
    import jellyfin_migrator
    import ubelt as ub

    # Get the path to the jellyfin migrator repo. we are going to copy the
    # entire thing in.
    repo_dpath = ub.Path(jellyfin_migrator.__file__).parent.parent

    # Create two jellyfin servers. One will be the source and one will be the
    # destination.
    self = apt_variant = JellyfinAptContainer(mounts=[
        {'source': repo_dpath, 'target': '/Jellyfin-Migrator'}
    ])
    apt_variant.reset()
    apt_variant.ensure()
    apt_variant.connect()

    # Clear any existing version of the code in the docker container, and
    # copy in a fresh copy of the latest code.
    self = apt_variant
    # Delete any previous migration data.
    self.call(['rm', '-rf', '/staging'])
    # Check that we can run Python
    self.start()
    self.connect()
    self.call(['python3', '--version'])
    # Run the migrator (with exec for stderr)
    _ = self.exec('apt update', cwd='/Jellyfin-Migrator', verbose=3)
    _ = self.exec('apt install python3-pip fd-find tree  --yes', cwd='/Jellyfin-Migrator', verbose=3)
    _ = self.exec('pip install pandas ubelt rich kwutil networkx', cwd='/Jellyfin-Migrator', verbose=3)

    # TODO: you might need to actually do something in the jellyfin server to
    # get it to populate jellyfin.db, otherwise maybe it is empty and this
    # fails?

    port = self.port
    username = 'jellyfin-user'
    password = 'jellyfin-pass'
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
    url = f'{url}:{port}'
    client.auth.connect_to_address(url)
    client.auth.login(url, username, password)
    client.jellyfin.get_users()
    client.jellyfin.get_media_folders()
    client.jellyfin.items()
    client.jellyfin.get_recently_added()
    client.jellyfin.new_user('other-user', 'other-password')
    client.jellyfin.unpause_sync_play()
    client.jellyfin.new_sync_play_v2('groupname')
    item = client.jellyfin.search_media_items()['Items'][0]
    client.jellyfin.refresh_item(item['Id'])
    client.jellyfin.set_item_sync_play(item['Id'])
    session = client.jellyfin.sessions()[0]
    client.jellyfin.remote_play_media(session['Id'], [item['Id']])

    # Re-running the server seems to do it?
    apt_variant.exec('apt update')
    apt_variant.exec('apt install psmisc sqlite3')
    apt_variant.exec('killall /usr/bin/jellyfin')
    apt_variant._run_server()

    _ = self.exec('du /root/.local/share/jellyfin/data/jellyfin.db', verbose=3)

    _ = self.exec('python3 -m jellyfin_migrator', cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')

    _ = self.exec('ls', cwd='/staging', verbose=3)
    # Check that the paths look like they updated correctly.
    # _ = self.exec('sqlite3 /root/.local/share/jellyfin/data/library.db "SELECT Path FROM TypedBaseItems;"', verbose=3)
    _ = self.exec('sqlite3 /staging/staged-data/data/library.db "SELECT Path FROM TypedBaseItems;"', verbose=3)

    dpath = ub.Path.appdir('jellyfin-migrator').ensuredir()
    local_staging = (dpath / 'staging').delete()
    self.copy_out('staging', to_path=local_staging)

    # TODO: ensure media paths have changed
    # sqlite3 library.db "SELECT Path FROM TypedBaseItems;"

    # Now lets try to port
    from jellyfin_migrator.demo.jellyfin_docker_variant import ensure_docker_variant
    # Hack:
    apt_variant.engine_cmd('stop jellyfin_demo_docker_variant')
    apt_variant.engine_cmd('rm jellyfin_demo_docker_variant')
    docker_variant = ensure_docker_variant(mounts=[
        {
            # hack
            'source': local_staging / 'staged-data',
            'target': '/config',
            'type': 'volume',
        }
    ], do_initial_configure=False)
    docker_variant.exec('apt update', verbose=3)
    docker_variant.exec('apt install rsync sqlite3 --yes', verbose=3)
    docker_variant.exec('du /config/data/jellyfin.db', verbose=3)
    docker_variant.exec('sha1sum /config/data/jellyfin.db', verbose=3)
    docker_variant.exec('sqlite3 /config/data/library.db "SELECT Path FROM TypedBaseItems;"', verbose=3)
    docker_variant.exec('sqlite3 /config/data/jellyfin.db -header -column "SELECT * FROM Users;"', verbose=3)

    # print(f'docker_variant.name={docker_variant.name}')
    # docker_variant.exec('rm -rf /staging')
    # docker_variant.copy_into(local_staging, '/staging')
    # docker_variant.exec('ls /', verbose=3)
    # docker_variant.exec('chmod +x /staging/accept.sh', verbose=3)
    # docker_variant.exec('cat /staging/accept.sh', verbose=3)
    # docker_variant.exec('sha1sum /staging/staged-data/data/jellyfin.db', verbose=3)
    # docker_variant.exec('sha1sum /config/data/jellyfin.db', verbose=3)
    # docker_variant.exec('ls -al /staging/staged-data/data/jellyfin.db', verbose=3)
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


def selenium_login():
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
        driver.get("http://localhost:8097/")

        wait = WebDriverWait(driver, 2)

        # Step 1: Check if "Connect to server" screen appears
        try:
            server_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Enter server address']")))
            connect_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Connect')]")))
            print("Entering server URL and clicking Connect")
            server_input.clear()
            server_input.send_keys("http://localhost:8097")
            connect_button.click()
        except Exception:
            print("Server connection screen not detected, proceeding to login")

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

if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/tests/test_end_to_end.py
    """
    main()
