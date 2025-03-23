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
    _ = self.exec('python3 -m jellyfin_migrator', cwd='/Jellyfin-Migrator', verbose=3, system=True, exec_args='-it')
    _ = self.exec('ls', cwd='/staging', verbose=3)

    dpath = ub.Path.appdir('jellyfin-migrator').ensuredir()
    local_staging = (dpath / 'staging').delete()
    self.copy_out('staging', to_path=local_staging)

    # Now lets try to port
    from jellyfin_migrator.demo.jellyfin_docker_variant import ensure_docker_variant
    docker_variant = ensure_docker_variant(mounts=[
        {
            # hack
            'source': local_staging / 'staged-data',
            'target': '/config',
            'type': 'volume',
        }
    ])
    print(f'docker_variant.name={docker_variant.name}')
    docker_variant.exec('rm -rf /staging')
    docker_variant.copy_into(local_staging, '/staging')
    docker_variant.exec('ls /', verbose=3)
    docker_variant.exec('chmod +x /staging/accept.sh', verbose=3)
    docker_variant.exec('apt update')
    docker_variant.exec('apt install rsync sqlite3 --yes')
    docker_variant.exec('cat /staging/accept.sh', verbose=3)
    docker_variant.exec('sha1sum /staging/staged-data/data/jellyfin.db', verbose=3)
    docker_variant.exec('sha1sum /config/data/jellyfin.db', verbose=3)
    docker_variant.exec('ls -al /staging/staged-data/data/jellyfin.db', verbose=3)
    docker_variant.exec('ls -al /config/data/jellyfin.db', verbose=3)
    docker_variant.exec('sqlite3 /', verbose=3)

    # docker_variant.exec('./accept.sh', cwd='/staging', verbose=3)
    # print(f'apt_variant.name={apt_variant.name}')

    # Ok, this isn't working why?
    # We can't login. Are we not copying the user credentials over?
    # Let's check that first.

if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/tests/test_end_to_end.py
    """
    main()
