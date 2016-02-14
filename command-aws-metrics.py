"""
This module calls the AWS ListMetrics() API followed by multiple calls to
GetMetricStatistics() to get metrics from AWS.

A dictionary configured by the 'metrics' key in the configuration file is
used to determine which metrics should lead to a call to GetMetricStatistics().

Each metric value returned from GetMetricStatistics() is sent to the Wavefront
proxy on port 2878 (or other port if configured differently).  Point tags
are picked up from the Dimensions.  Source is determined by searching
the point tags for a list of "accepted" source locations 
(e.g., 'Service', 'LoadBalancerName', etc).

The last run time is stored in a configuration file in 
/opt/wavefront/etc/aws_metrics.json.conf and will be used on the next run to 
determine the appropriate start time.  If no configuration file is found, 
the start time is determined by subtracting the delay_minutes from the 
current time.

This script should be run by cron on a regular schedule.  For example, to
run this script every 5 minutes add this to your crontab:
*/5 * * * * /path/to/script.py
"""

import argparse
import command
import boto3
import datetime
import dateutil
import json
import logging
import numbers
import os
import re
import socket
import sys
import time


# Configuration for metrics that should be retrieved is contained in this
# configuration in a "metrics" key.  This is a dictionary
# where the key is a regular expression and the value is an object with keys:
#    * stats
#        a list of statistics to pull down with the GetMetricStatistics() call.
#        valid values are any of : 'Average', 'Maximum', 'Minimum', "SampleCount', 'Sum'
#    * source_names
#        an array of :
#          - tag names (Dimensions)
#          - Dimensions array index (0 based)
#          - String literals
#        The first match is returned as the source name.  if source_names is
#        not present in the configuration, default_source_names array is used.
#
# The key to the dictionary is a regular expression that should match a:
#     <namespace>.<metric_name> (lower case with /=>.)
#
DEFAULT_CONFIG_FILE = os.path.dirname(__file__) + '/../etc/aws-metrics.json.conf'

# List of potential key names for the source/host value (can be overriden
# in the above namespace configuration)
# A numeric value in this means that that index in the Dimensions is chosen
default_source_names = ['Service', 'AvailabilityZone', 0, 'Namespace', '=AWS']

# Mapping for statistic name to its "short" name.  The short name is used
# in the metric name sent to Wavefront
stat_short_name = {
    'Average': 'avg',
    'Minimum': 'min',
    'Maximum': 'max',
    'Sum': 'sum',
    'SampleCount': 'count'
}

# Wavefront Proxy context manager for managing the socket connection to proxy
class WavefrontProxy(object):
    def __init__(self, host, port, dry_run = False):
        super(WavefrontProxy, self).__init__()
        self.is_dry_run = dry_run
        self.host = host
        self.port = port
        self.sock = None

    def transmit_metric(self, name, value, ts, source, point_tags):
        """
        Transmit metric to the proxy
        """

        line = '{} {} {} source={}'.format(name, value, ts, source)
        if point_tags is not None:
            for k, v in point_tags.iteritems():
                line = line + ' {}={}'.format(k, v)

        if self.is_dry_run:
            print '[{}:{}] {}'.format(self.host, self.port, line)

        else:
            self.sock.sendall('%s\n' % line)

    def __enter__(self):
        if not self.is_dry_run:
            self.sock = socket.socket()
            self.sock.connect((self.host, self.port))

        return self

    def __exit__(self, type, value, traceback):
        if self.sock is not None and not self.is_dry_run:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()


class AwsMetricsCommand(command.Command):
    def __init__(self, **kwargs):
        super(AwsMetricsCommand, self).__init__(**kwargs)
        self.config_file_path = DEFAULT_CONFIG_FILE
        self.is_dry_run = False
        self.proxy_host = '127.0.0.1'
        self.proxy_port = 2878
        self.has_suffix_for_single_stat = True
        # delay minutes is the number of minutes of data to request the first
        # time this is run (subsequent runs will use the last run timestamp
        # in the configuration file)
        self.default_delay_minutes = 5
        self.metric_name_prefix = ''
        self.aws_client = None
        self.last_run_timestamp = None
        self.metrics_config = None

    def load_configuration(self):
        """
        Loads the configuration from the configuration file.
        """
        if not os.path.exists(self.config_file_path):
            raise ValueError('ERROR: Configuration file (' + self.config_file_path + ') does not exist')

        with open(self.config_file_path, 'r') as cf:
            config = json.load(cf)

        if 'metrics' not in config:
            raise ValueError('ERROR: Configuration file (' + self.config_file_path + ') is not valid')

        self.metrics_config = config['metrics']
        if 'last_run_timestamp' in config:
            self.last_run_timestamp = long(config['last_run_timestamp'])


    def update_last_runtime(self, end):
        """
        write out the updated configuration with the last_run_timestamp
        :param end: the current end time last used with ListMetrics()
        """

        with open(self.config_file_path, 'r+') as cf:
            config = json.load(cf)
            config['last_run_timestamp'] = command.unix_time_millis(end) / 1000
            cf.seek(0)
            json.dump(config, cf)
            cf.truncate()
    
    def add_arguments(self, parser):
        """
        Adds arguments supported by this command to the argparse parser
        :param parser: the argparse parser created using .add_parser()
        """

        parser.add_argument('--config',
                            default = self.config_file_path,
                            help = 'Path to configuration file')
        parser.add_argument('--proxy',
                            default = self.proxy_host + ':' + str(self.proxy_port),
                            help = 'The host name (or IP address) and port of Wavefront proxy')
        parser.add_argument('--dry-run',
                            default = self.is_dry_run,
                            help = 'Dry run (don\'t send data to proxy just print to STDOUT)',
                            action = 'store_true')
        parser.add_argument('--no-suffix-for-single',
                            default = not self.has_suffix_for_single_stat,
                            action = 'store_true',
                            help = 'Don\'t add the statistics suffix when there is only a single stat being collected for a metric')
        parser.add_argument('--prefix',
                            default = self.metric_name_prefix,
                            help = 'Add this prefix to the metric names')
        parser.add_argument('--role-arn',
                            help = argparse.SUPPRESS)
        parser.add_argument('--role-session-name',
                            help = argparse.SUPPRESS)

    def _parse_args(self, a):
        """
        Parses the arguments passed into this command
        :param a: the argparse parser object returned from parser.parse_args()
        """

        self.config_file_path = a.config
        self.is_dry_run = a.dry_run
        if a.proxy:
            c = a.proxy.find(':')
            if c:
                self.proxy_host = a.proxy[0:c]
                self.proxy_port = int(a.proxy[c+1:])
            else:
                self.proxy_host = a.proxy
                self.proxy_port = 2878
        else:
            self.proxy_host = '127.0.0.1'
            self.proxy_port = 2878

        self.has_suffix_for_single_stat = a.no_suffix_for_single
        self.metric_name_prefix = a.prefix
        self.roleARN = a.role_arn
        self.roleSessionName = a.role_session_name

    def get_configuration(self, namespace, metric_name):
        """
        Given a namespace and metric, get the configuration
        :param namespace: the namespace
        :param metric_name: the metric's name
        :return the configuration for this namespace and metric
        """

        current_match = None
        m = namespace.replace('/', '.').lower() + '.' + metric_name.lower()
        for n, c in self.metrics_config.iteritems():
            if re.match(n, m, re.IGNORECASE):
                if current_match is None or \
                   ('priority' in current_match and \
                    current_match['priority'] < c['priority']):
                    current_match = c

        return current_match

    def _get_source(self, config, point_tags, dimensions):
        """
        Determine the source from the point tags.
        """

        if 'source_names' in config:
            source_names = config['source_names']
        else:
            source_names = default_source_names

        for n in source_names:
            if isinstance(n, numbers.Number):
                if len(dimensions) < n:
                    return dimensions[n]
                else:
                    continue

            if n[0:1] == '=':
                return n[1:]

            if n in point_tags:
                return point_tags[n]

        return None

    def _process_metrics(self, metrics, start, end):
        """
        Loops over all metrics and call GetMetricStatistics() on each that are
        included by the configuration.
        :param metrics: the array of metrics returned from ListMetrics() ('Metrics')
        :param start: the start time
        :param end: the end time
        """

        with WavefrontProxy(self.proxy_host, self.proxy_port, self.is_dry_run) as wf_proxy:
            for m in metrics:
                metric_name = '{}.{}'.format(m['Namespace'].lower().replace('/', '.'),
                                             m['MetricName'].lower())
                point_tags = {'Namespace': m['Namespace']}
                for d in m['Dimensions']:
                    point_tags[d['Name']] = d['Value']

                config = self.get_configuration(m['Namespace'], m['MetricName'])
                if config is None or len(config['stats']) == 0:
                    continue

                stats = self.aws_client.get_metric_statistics(
                    Namespace = m['Namespace'],
                    MetricName = m['MetricName'],
                    StartTime = start,
                    EndTime = end,
                    Period = 60,
                    Statistics = config['stats'])
                source = self._get_source(config, point_tags, m['Dimensions'])
                if not source:
                    logger.warning('Source is not found in %s', m)
                    continue

                number_of_stats = len(config['stats'])
                for stat in stats['Datapoints']:
                    for s in config['stats']:
                        short_name = stat_short_name[s]
                        if number_of_stats == 1 and self.has_suffix_for_single_stat:
                            full_metric_name = metric_name
                        else:
                            full_metric_name = metric_name + '.' + short_name

                        wf_proxy.transmit_metric(
                            self.metric_name_prefix + full_metric_name,
                            stat[s],
                            command.unix_time_millis(stat['Timestamp']),
                            source,
                            point_tags)

    def get_help_text(self):
        return "Pull metrics from AWS CloudWatch and push them into Wavefront"

    def _execute(self):
        """
        Execute this command
        """

        if self.roleARN is not None:
            # assume role (for testing internally)
            c = boto3.client('sts')
            r = c.assume_role(
                RoleArn = self.roleARN,
                RoleSessionName = self.roleSessionName)
            s = boto3.Session(r['Credentials']['AccessKeyId'],
                              r['Credentials']['SecretAccessKey'],
                              r['Credentials']['SessionToken'])
            self.aws_client = s.client('cloudwatch')

        else:
            self.aws_client = boto3.client('cloudwatch')
    
        self.load_configuration()

        # start/end time
        end = datetime.datetime.utcnow().replace(tzinfo = dateutil.tz.tzutc())
        if self.last_run_timestamp:
            start = datetime.datetime.utcfromtimestamp(self.last_run_timestamp).replace(tzinfo = dateutil.tz.tzutc())
            if (end - start).total_seconds() > 86400:
                start = end - datetime.timedelta(days=1)
        else:
            start = end - datetime.timedelta(minutes = self.default_delay_minutes)

        # ListMetrics() API
        response = self.aws_client.list_metrics()
        metrics_available = 'Metrics' in response
        while metrics_available:
            self._process_metrics(response['Metrics'], start, end)
            if 'NextToken' in response:
                response = self.aws_client.list_metrics(
                    NextToken = response['NextToken'])
                metrics_available = 'Metrics' in response
            else:
                metrics_available = False

        self.update_last_runtime(end)

