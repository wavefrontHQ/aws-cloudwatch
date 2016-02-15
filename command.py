import datetime
import dateutil
import dateutil.tz
import os.path
import ConfigParser

epoch = datetime.datetime.utcfromtimestamp(0).replace(tzinfo = dateutil.tz.tzutc())
def unix_time_millis(dt):
    """
    Helper function to get a unix timestamp for the given datetime object
    in milliseconds since epoch
    :param dt: the datetime object to retrieve the timestamp for
    """
    return long((dt - epoch).total_seconds() * 1000)

class Command(object):
    """
    This is the base class of each command implemented.
    """

    def __init__(self, **kwargs):
        super(Command, self).__init__()
        self.verbose = False

    def _parse_args(self, args):
        """
        Parses the command specific arguments out.
        :param args: list of arguments
        """

        raise ValueError('command:parse_args() should be implemented by subclass')

    def add_arguments(self, parser):
        """
        Adds this command's arguments to the argsparser object
        """

        raise ValueError('command:parse_args() should be implemented by subclass')

    def execute(self, args):
        """
        Execute this command with the given arguments
        """

        self._parse_args(args)
        self._execute()

    def _execute(self):
        raise ValueError('command:_execute() should be implemented by subclass')

    def get_help_text(self):
        """
        Gets the text to display for this command.
        """

        return ""

    def output_verbose(self, msg):
        """
        Very simple function to output to stdout if verbose flag is set
        :param msg the message to output
        """

        if self.verbose:
            print msg

class WavefrontClientCommand(Command):
    """
    Abstract class for commands that will access the Wavefront client.
    """

    def __init__(self, **kwargs):
        super(WavefrontClientCommand, self).__init__(**kwargs)

    def _load_wf_api(self):
        """
        Attempts to load the Wavefront client.  Will check the environment,
        standard configuration file for base url and token.
        """

        import wavefrontapi.wf_exceptions
        import wavefrontapi
        try:
            config = ConfigParser.ConfigParser()
            config.read(os.path.expanduser('~') + '/.wavefront')
        except IOError:
            # ignore this - assumed cause is filenotfound
            config = None
        
        token = os.getenv('WAVEFRONT_API_KEY', None)
        if token is None and config is not None and config.has_section('api'):
            token = config.get('api', 'key')
        if token is None or token[0:3] == 'SET':
            print 'Please set the api.key configuration key in ~/.wavefront or WAVEFRONT_API_KEY environment variable prior to running this script'
            raise wavefrontapi.wf_exceptions.APITokenRequired()

        base_url = os.getenv('WAVEFRONT_API_BASE_URL', None)
        if base_url is None and config is not None and config.has_section('api'):
            base_url = config.get('api', 'base_url')
        if base_url is None or base_url[0:3] == 'SET':
            print 'Please set the api.key configuration key in ~/.wavefront or WAVEFRONT_API_KEY environment variable prior to running this script'
            raise wavefrontapi.wf_exceptions.APIBaseURLRequired()

        wavefrontapi.api_url = base_url
        wavefrontapi.api_key = token
