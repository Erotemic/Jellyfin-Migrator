import ubelt as ub
from jellyfin_migrator.demo.oci_container import OCIContainer, OCIContainerEngineConfig
from jellyfin_migrator.demo.demo_media import grab_demo_media
from jellyfin_migrator.demo.jellyfin_init import JellyfinInitializer
from jellyfin_migrator.demo.jellyfin_init import is_server_alive, is_server_alive2


class JellyfinAptContainer(OCIContainer):
    """
    Defines an Ubuntu 22.04 image that can setup a jellyfin server.
    """

    def __init__(self, port=8098, oci_engine='docker', mounts=None, use_image_cache=True):
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

        # Logic so we can save a server in a fresh state as a standalone image
        # which lets us iterate faster. This is kinda hacky, and could be
        # cleaned up. We should put the setup file into a standalone docker
        # file and just build it. But this requires some special handling
        # so we can auto-initialize the server credentials.
        self.base_image = 'ubuntu:22.04'
        container_name = 'jellyfin_demo_apt_variant'
        self.cached_image = 'jellyfin_demo_apt_image'
        self.use_image_cache = use_image_cache

        if use_image_cache and self.image_exists(self.cached_image):
            # Use a presetup image.
            image = self.cached_image
        else:
            image = self.base_image

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
            image=image,
            name=container_name,
            engine=engine
        )

    @classmethod
    def image_exists(self, image_name):
        info = ub.cmd('docker images --format "{{.Repository}}:{{.Tag}}"')
        existing_image_names = info['out'].split('\n')
        return image_name in existing_image_names or (image_name + ':latest') in existing_image_names

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
        return self

    def reset(self):
        self.remove(force=True, volumes=True)
        self.create()
        self.start()
        if self.image == self.base_image:
            self.setup_server()
        return self

    def is_alive(self):
        # FIXME: this doesn't work all the time for some reason
        return is_server_alive(self.port, verbose=0)

    def is_alive_fallback(self):
        assert self.name is not None, 'container name should exist'
        running_procs = self.exec('ps -ax').stdout
        if '/usr/bin/jellyfin' in running_procs:
            return is_server_alive2(self.port)

    def _run_server(self):
        import time
        assert self.name is not None, 'container name should exist'
        ub.cmd(f'docker exec --detach {self.name} /usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg')
        wait_time = 0

        prog = ub.ProgIter(desc='waiting for server to respond...')
        with prog:
            # Block until server is online
            while not self.is_alive():
                prog.step()
                time.sleep(0.1)
                wait_time += 1
                if wait_time > 20:
                    if self.is_alive_fallback():
                        break

    def setup_server(self):
        """
        Only run on an uninitialized server
        """
        # Write the script into the container an call it to setup the server.
        setupscript_text = ub.codeblock(
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
            ''')

        DEV_GOODIES = True
        if DEV_GOODIES:
            setupscript_text += '\n' + ub.codeblock(
                '''
                apt install python3-pip --yes
                apt install fd-find tree --yes
                pip install pandas ubelt rich kwutil networkx
                ''')

        # TODO:
        # maybe fix systemctl with
        # https://stackoverflow.com/questions/46800594/start-service-using-systemctl-inside-docker-container
        ub.codeblock(
            '''
            # Use this to run jellyfin instead of systemctl
            #/usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg
            # Does not work because systemctl is not available in the container
            # systemctl start jellyfin
            # systemctl status jellyfin --no-pager
            ''')

        fpath = ub.Path.appdir('jellyfin/demo').ensuredir() / 'setup_apt_server.sh'
        fpath.write_text(setupscript_text)
        self.copy_into(fpath, ub.Path(fpath.name))
        self.call(['bash', 'setup_apt_server.sh'])
        # import time
        # time.sleep(3)
        # Start the server
        print('Starting the server')
        self._run_server()

        # Initialize the server with a user/pass: jellyfin-user/jellyfin-pass
        print('Configuring server')
        initializer = JellyfinInitializer(port=self.port,
                                          username='jellyfin-user',
                                          password='jellyfin-pass')

        initializer.configure_initial_server()

        # Add media for the server to manage
        print('Adding media libraries')
        initializer.add_demo_media_libraries(
            media_dpath=self.internal_media_dpath
        )

        if self.cached_image:
            self.commit(self.cached_image)

    def save_cache(self):
        assert self.image == self.base_image
        self.commit(self.cached_image)


def main():
    """
    Standalone entry point that ensures the server is setup and running.
    """
    self = JellyfinAptContainer()
    self.reset()
    self.ensure()


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/jellyfin_migrator/demo/jellyfin_apt_variant.py
    """
    main()
