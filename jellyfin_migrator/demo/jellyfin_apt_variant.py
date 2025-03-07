import ubelt as ub
from jellyfin_migrator.demo.oci_container import OCIContainer, OCIContainerEngineConfig
from jellyfin_migrator.demo.demo_media import grab_demo_media
from jellyfin_migrator.demo.jellyfin_init import configure_initial_server
from jellyfin_migrator.demo.jellyfin_init import add_demo_media_libraries
from jellyfin_migrator.demo.jellyfin_init import is_server_alive


class JellyfinAptContainer(OCIContainer):
    """
    Defines an Ubuntu 22.04 image that can setup a jellyfin server.
    """

    def __init__(self, port=8098, oci_engine='docker', mounts=None):
        self.port = port

        # Always mount the demo media path
        paths = grab_demo_media()
        media_dpath = paths['media']
        self.internal_media_dpath = '/data/jellyfin/media'
        _mounts = [
            {'source': media_dpath, 'target': self.internal_media_dpath}
        ]
        if mounts is not None:
            _mounts.extend(mounts)

        mount_args = []
        for mount in _mounts:
            mount_args.append('--mount')
            source = mount['source']
            target = mount['target']
            mount_args.append(f'type=bind,source={source},target={target}')

        engine = OCIContainerEngineConfig(
            oci_engine,
            disable_host_mount=True,
            create_args=(
                '--publish',
                f'{port}:8096/tcp',
                *mount_args
            )
        )
        super().__init__(
            image='ubuntu:22.04',
            name='jellyfin_demo_apt_variant',
            engine=engine
        )

    def ensure(self):
        """
        Check if the server is running, if not, create and set it up.
        """
        print('Ensuring server')
        if self.running():
            print('Ensuring is running, connecting')
            self.connect()
        elif self.exists():
            print('Ensuring is not running, but exists, starting')
            self.start()
            print('... connecting')
            self.connect()
        else:
            print('Ensuring does not exist, needs to be created')
            self.create()
            print('... starting')
            self.start()
            print('... setup')
            self.setup_server()
        if not self.is_alive():
            print('server is not alive, need to run')
            self._run_server()
        else:
            print('server is alive')

    def reset(self):
        self.remove(force=True, volumes=True)
        self.create()
        self.start()
        self.setup_server()

    def is_alive(self):
        # FIXME: this doesn't work all the time for some reason
        return is_server_alive(self.port)

    def _run_server(self):
        import time
        ub.cmd(f'docker exec --detach {self.name} /usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg')
        # Block until server is online
        while not self.is_alive():
            print('waiting')
            time.sleep(0.1)

    def setup_server(self):
        """
        Only run on an uninitialized server
        """
        # Write the script into the container an call it to setup the server.
        text = ub.codeblock(
            '''
            #!/usr/bin/env bash
            export DEBIAN_FRONTEND=noninteractive
            apt update
            apt-get install software-properties-common -y
            apt install curl gnupg -y
            add-apt-repository universe

            mkdir -p /etc/apt/keyrings
            curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor -o /etc/apt/keyrings/jellyfin.gpg

            cat <<EOF | tee /etc/apt/sources.list.d/jellyfin.sources
            Types: deb
            URIs: https://repo.jellyfin.org/$( awk -F'=' '/^ID=/{ print $NF }' /etc/os-release )
            Suites: $( awk -F'=' '/^VERSION_CODENAME=/{ print $NF }' /etc/os-release )
            Components: main
            Architectures: $( dpkg --print-architecture )
            Signed-By: /etc/apt/keyrings/jellyfin.gpg
            EOF

            apt update
            apt install jellyfin -y

            # Use this to run jellyfin instead of systemctl
            #/usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg
            # Does not work because systemctl is not available in the container
            # systemctl start jellyfin
            # systemctl status jellyfin --no-pager
            ''')

        # TODO:
        # maybe fix systemctl with
        # https://stackoverflow.com/questions/46800594/start-service-using-systemctl-inside-docker-container

        fpath = ub.Path.appdir('jellyfin/demo').ensuredir() / 'setup_apt_server.sh'
        fpath.write_text(text)
        self.copy_into(fpath, ub.Path(fpath.name))
        self.call(['bash', 'setup_apt_server.sh'])
        # import time
        # time.sleep(3)
        # Start the server
        print('Starting the server')
        self._run_server()

        # Initialize the server with a user/pass: jellyfin/jellyfin
        print('Configuring server')
        configure_initial_server(self.port)

        # Add media for the server to manage
        print('Adding media libraries')
        add_demo_media_libraries(self.port, media_dpath=self.internal_media_dpath)


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/jellyfin_migrator/demo/jellyfin_apt_variant.py
    """
    JellyfinAptContainer().ensure()
