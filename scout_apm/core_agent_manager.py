# TODO:
#   x How to ask an existing agent who it is & what version
#   x Should we politely ask an existing agent to shutdown?
#   * Core agent stdin/stdout? - should close, or try to proxy back to python?
#       - popen is keeping it linked to the same stdin/out
#   x Where do we download to
#   x Where do we unpack the binary
#   * What to do if we don't have the arch/version hosted?
#   * What workflow for user-launched core agent?
#   * Build script to build different versions
#   * Launch style - fork/exec w/ command line options
#   * How to shut down python
#   * Core Agent updates itself?
#   * support "download" from a local file path
#   * forking webservers? Don't download for each fork
#     * apache/mod_wsgi
#     * gunicorn
#
#  Error cases:
#    * download fails
#    * disk space runs out (download or unpack)
#    * download doesn't verify sha
#    * core agent doesn't launch
#    * Unknown platform
#
#  Build process
#    * for each environment,
#      * build
#      * create metadata
#      * tar
#    * s3 bucket
#      * downloads.scoutapp.com/core_agent/....
#
#  scout_apm_core-latest_metadata.txt - ~1k
#  scout_apm_core-latest.tgz
#  |- scout_apm_core-1.2.3-linux-x86_64
#  |- manifest.txt
#
#     metadata something like:
#     { version: 1
#       core_binary: scout_apm_core-1.2.3-linux-x86_64
#       core_binary_sha256: 0123456ABCDEFG...
#     }
#
#           x detect version (default or specified in config)
#           - specify SSL CA file?
#           x where to download from/to
#           x platform
#           x architecture
#           x root url for tgz
#           x proxy (python urllib reads from http_proxy/https_proxy env var)
#           x sha256sum the downloaded file, compare to metadata
#           x launch - how?

import hashlib
import platform
import tarfile
import urllib.request
import subprocess
import tempfile
import json
import atexit
import shutil

from scout_apm.context import agent_context
from scout_apm.socket import CoreAgentSocket
from scout_apm.commands import CoreAgentVersion, CoreAgentVersionResponse, CoreAgentShutdown


class CoreAgentManager:
    def launch(self):
        # Kill any running core agent
        probe = CoreAgentProbe()
        if probe.is_running():
            print('Trying to shutdown an already-running CoreAgent')
            probe.shutdown()

        # Obtain the CoreAgent we want
        self.downloader = CoreAgentDownloader()
        self.downloader.download()
        print('Downloaded CoreAgent version:', self.downloader.version)
        executable = self.downloader.executable

        atexit.register(self.atexit, self.downloader.destination)

        # Launch the CoreAgent we want
        self.run(executable)
        print('Launching')

    def run(self, executable):
        subprocess.Popen(
                [
                    executable, 'daemon',
                    '--api-key', 'Qnk5SKpNEeboPdeJkhae',
                    '--log-level', 'info',
                    '--app-name', 'CoreAgent',
                    '--socket', self.socket_path()
                ])

    def socket_path(self):
        print('Socket path', agent_context.config.value('socket_path'))
        return agent_context.config.value('socket_path')

    def atexit(self, directory):
        print('Atexit shutting down agent')
        CoreAgentProbe().shutdown()
        print('Atexit deleting directory:', directory)
        shutil.rmtree(directory)


class CoreAgentDownloader():
    def __init__(self):
        self.destination = tempfile.mkdtemp()
        self.package_location = self.destination + '/download.tgz'

    def download(self):
        self.download_package()
        self.untar()
        self.verify()

    def download_package(self):
        print('Downloading: {full_url} to {filepath}'.format(
            full_url=self.full_url(),
            filepath=self.package_location))
        urllib.request.urlretrieve(self.full_url(), self.package_location)

    def untar(self):
        t = tarfile.open(self.package_location, 'r')
        t.extractall(self.destination)

    # Read the manifest, check the sha256 checksum, and set variables needed
    def verify(self):
        manifest = CoreAgentManifest(self.destination + '/manifest.txt')
        executable = self.destination + '/' + manifest.executable
        if SHA256.digest(executable) == manifest.sha256:
            self.version = manifest.version
            self.executable = executable
            return True
        else:
            raise 'Failed to verify'

    def full_url(self):
        return '{root_url}/{binary_name}.tgz'.format(
                root_url=self.root_url(),
                binary_name=self.binary_name())

    def root_url(self):
        return agent_context.config.value('download_url')

    def binary_name(self):
        return 'scout_apm_core-{version}-{platform}-{arch}'.format(
                version=self.download_version(),
                platform=self.platform(),
                arch=self.arch())

    def platform(self):
        system_name = platform.system()
        if system_name == 'Linux':
            return 'linux'
        elif system_name == 'Darwin':
            return 'darwin'
        else:
            return 'unknown'

    def arch(self):
        arch = platform.machine()
        if arch == 'i386':
            return 'i386'
        elif arch == 'x86_64':
            return 'x86_64'
        else:
            return 'unknown'

    def download_version(self):
        return agent_context.config.value('download_version')


class CoreAgentManifest:
    def __init__(self, path):
        self.raw = open(path).read()
        self.parse()

    def parse(self):
        self.json = json.loads(self.raw)
        self.version = self.json['version']
        self.executable = self.json['core_binary']
        self.sha256 = self.json['core_binary_sha256']


class CoreAgentProbe():
    def is_running(self):
        return self.version() is not None

    # Returns a CoreAgentVersion or None
    def version(self):
        try:
            socket = self.build_socket()
            response = socket.send(CoreAgentVersion())
            self.version = CoreAgentVersionResponse(response).version
            print('version:', self.version)
            return self.version
        except Exception as e:
            print('Existing CoreAgent is not running')
            return None

    def shutdown(self):
        try:
            socket = self.build_socket()
            socket.send(CoreAgentShutdown())
            print('Shut down existing CoreAgent')
        except:
            print('Attempted, but failed to shutdown core agent. Maybe it\'s already stopped?')

    def build_socket(self):
        socket_path = agent_context.config.value('core_agent_socket')
        socket = CoreAgentSocket(socket_path)
        socket.open()
        return socket


class SHA256:
    @staticmethod
    def digest(filename, block_size=65536):
        sha256 = hashlib.sha256()
        with open(filename, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                sha256.update(block)
        return sha256.hexdigest()
