# Overview
This script calls the AWS [ListMetrics()](http://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_ListMetrics.html) API followed by multiple calls to [GetMetricStatistics()](http://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html) to get metrics from AWS.

The primary purpose of this script is to retrieve more statistics for a given metric than are currently obtained via the external integration.

A dictionary configured by the 'metrics' key in the configuration file is
used to determine which metrics should lead to a call to GetMetricStatistics().

Each metric value returned from GetMetricStatistics() is sent to the Wavefront
proxy on port 2878 (or other port if configured differently).  Point tags
are picked up from the Dimensions object in the AWS response.
Source is determined by searching the point tags for a list of "accepted"
source locations (e.g., 'Service', 'LoadBalancerName', etc).

The last run time is stored in a configuration file in 
/opt/wavefront/etc/aws_metrics.json.conf and will be used on the next run to 
determine the appropriate start time.  If no configuration file is found, 
the start time is determined by subtracting the delay_minutes from the 
current time.

This should be run by cron on a regular schedule.  See details below for more information.

# Installation
1. This script is written in Python and relies on the boto3 package.  You’ll need to install that package before running.  You can do that with this command:
```$ pip install --user boto3```
or
```$ sudo pip install boto3```

  (If you don’t have `pip` you can install it with: `$ sudo apt-get install python-pip`)

2. Setup your AWS credentials.   Create a file in ~/.aws.credentials that looks like this:
[default]
aws_access_key_id=<YOUR ACCESS KEY ID>
aws_secret_access_key=<YOUR SECRET KEY>

# Configuration
aws_metrics.json.conf file contains the configuration for this script.  The format looks like this:
```javascript
{
    "metrics": {
        "aws\\.service_name\..*": {
            "stats": [
                "Average",
                "Maximum"
            ],
            "priority": 0
        },
        ...

```

Add one configuration object and key for each metric to be collected.  The key can be a regular expression matching more than one metric.  Metric names are determined by converting the namespace to lowercase and replacing "/" with ".".

The configuration object has the following supported attributes:
|Attribute Name|Type|Description|
|--------------|----|-----------|
|stats         |array of strings|A list of stats to collect.  Allowed values include: 'Average', 'Minimum', 'Maximum', 'Sum', 'SampleCount'.|
|'priority'| number | Optional.  Priority of this configuration.  Only used when there are multiple matches for the same configuration name|



# Run
./wavefront.py aws-metrics --config ./aws_metrics.json.conf --proxy localhost:2878 —no-suffix-for-single

This will connect to the AWS API, grab the metrics including all the stats configured in the configuration file and then send those to the proxy listening on port 2878.

# Run on a Regular Schedule
The script is designed to be run by cron.  Add an entry to your wavefront user’s crontab to run as often as you like.

Modify the crontab for the user that will be running the script
`$ crontab -e`

To run the script every minute, copy this into the first line and save
`* * * * * <PATH TO EXTRACTED FILES>/wavefront.py aws-metrics --config <PATH TO EXTRACTED FILES>/aws_metrics.json.conf --proxy localhost:2878 —no-suffix-for-single`

or to run every 2 minutes use:
`*/2 * * * * <PATH TO EXTRACTED FILES>/wavefront.py aws-metrics --config <PATH TO EXTRACTED FILES>/aws_metrics.json.conf --proxy localhost:2878 —no-suffix-for-single`

(Be sure to change '<PATH TO EXTRACTED FILES>’ to the path where you extracted the files from our last email.)
