# import ubelt as ub
from jellyfin_migrator.demo.oci_container import OCIContainer, OCIContainerEngineConfig
from jellyfin_migrator.demo.demo_media import grab_demo_media
from jellyfin_migrator.demo.jellyfin_init import configure_initial_server


class JellyfinDockerContainer(OCIContainer):
    """
    Defines an official jellyfin docker container.
    """
    def __init__(self, port=8097, oci_engine='docker', mounts=None):
        # Always mount the demo media path
        paths = grab_demo_media()
        media_dpath = paths['media']
        self.internal_media_dpath = '/media'
        _mounts = [
            {'source': media_dpath, 'target': self.internal_media_dpath}
        ]
        if mounts is not None:
            _mounts.extend(mounts)

        mount_args = []
        for mount in _mounts:
            source = mount['source']
            target = mount['target']
            mtype = mount.get('type', 'bind')
            if mtype == 'bind':
                mount_args.append('--mount')
                mount_args.append(f'type={mtype},source={source},target={target}')
            elif mtype == 'volume':
                # mount_args.append(f'type={mtype},{source}:{target}')
                mount_args.append('--volume')
                mount_args.append(f'{source}:{target}')
            else:
                raise AssertionError

        self.base_image = 'jellyfin/jellyfin'
        container_name = 'jellyfin_demo_docker_variant'
        image = self.base_image
        self.port = port

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

    def ensure(self, do_initial_configure=False):
        if self.running():
            self.connect()
        elif self.exists():
            self.start()
            self.connect()
        else:
            import time
            self.create()
            self.start()
            # Query the container until it is ready
            while not self.status() == 'running':
                time.sleep(0.1)
            if do_initial_configure:
                configure_initial_server(self.port)


def ensure_docker_variant(mounts=None, do_initial_configure=False):
    paths = grab_demo_media()
    media_dpath = paths['media']
    port = 8097

    _mounts = [
        {'source': media_dpath, 'target': '/media'}
    ]
    if mounts is not None:
        _mounts.extend(mounts)

    mount_args = []
    for mount in _mounts:
        source = mount['source']
        target = mount['target']
        mtype = mount.get('type', 'bind')
        if mtype == 'bind':
            mount_args.append('--mount')
            mount_args.append(f'type={mtype},source={source},target={target}')
        elif mtype == 'volume':
            # mount_args.append(f'type={mtype},{source}:{target}')
            mount_args.append('--volume')
            mount_args.append(f'{source}:{target}')
        else:
            raise AssertionError

    engine = OCIContainerEngineConfig(
        "docker",
        disable_host_mount=True,
        create_args=(
            '--publish',
            f'{port}:8096/tcp',
            *mount_args
        )
    )
    self = OCIContainer(image='jellyfin/jellyfin',
                        name='jellyfin_demo_docker_variant',
                        engine=engine)
    if self.running():
        self.connect()
    elif self.exists():
        self.start()
        self.connect()
    else:
        import time
        self.create()
        self.start()
        # Query the container until it is ready
        while not self.status() == 'running':
            time.sleep(0.1)
        if do_initial_configure:
            configure_initial_server(port)
    return self


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/jellyfin_migrator/demo/jellyfin_docker_variant.py
    """
    ensure_docker_variant()
