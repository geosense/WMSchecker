#!/usr/bin/env python2
"""Script for testing given OGC WMS services

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

__license__ = 'GNU/GPL'
__author__ = 'jachym.cepicky at geosense dot cz'
__version__ = '1.0.0'

import json
from tqdm import tqdm
from owslib.wms import WebMapService
from jinja2 import Environment, PackageLoader
import base64
import datetime
import traceback
import sys
import logging
import argparse

FILE = 'urls.json'

logging.basicConfig(level=logging.ERROR)


def test_layer(service, name):
    """
    Test given layer name from given WMS service
    """

    result = {}
    is_image = None
    data = None
    if service.contents.has_key(name):
        content = service.contents[name]
        response = service.getmap(
            layers=[name],
            srs=content.boundingBox[-1],
            bbox=content.boundingBox[:-1],
            format='image/png',
            size=[20, 20]
        )
        data = response.read()

        is_image = data[:8] == "\211PNG\r\n\032\n"

        if is_image:
            data = base64.b64encode(data)
    else:
        data = 'Layer "%s" is not available' % name

    result = {
        'is_image': is_image,
        'content': data
    }
    return result


def test_layers(service, inlayers=None):
    """Test layers of given name from given WMS service
    """

    layers = {}
    if not inlayers:
        for name in service.contents:
            layers[name] = test_layer(service, name)
    else:
        for name in inlayers:
            layers[name] = test_layer(service, name)
    return layers


def test_service(record):
    """Test given service based on configuration record
    dictionary with at least 'url' attribute
    """

    url = record['url']
    # version = '1.3.0'
    # if record.get('version'):
    #    version = record['version']

    exception = None
    result = True
    layers = []
    service = None
    title = None

    try:
        service = WebMapService(url)
    except Exception as e:
        result = False
        exception = traceback.format_exc()

    if 'title' in record:
        title = record['title']

    if service:
        layers = None
        if 'layers' in record:
            layers = record['layers']
        layers = test_layers(service, layers)
        for layer in layers:
            if not layers[layer]['is_image']:
                result = False
                break

    result = {
        'url': url,
        'title': title,
        'layers': layers,
        'passed': result,
        'exception': exception
    }

    return result


def test_services(data):
    """Test all services from configuration
    data format:

    [
        {
            'url': 'http://...',
            'layers': ['layer1', 'layer2'], #optional
            'title': 'Title' # optional
        }
    ]
    """

    results = []
    for record in tqdm(data):
        service_result = test_service(record)
        results.append(service_result)

    return results


def make_report(outfile, results, outformat='html'):
    """Save output report to given outname file
    Default is stdout
    """

    report = None
    if outformat == 'html':
        env = Environment(loader=PackageLoader('wmschecker', 'templates'))
        report_template = env.get_template('report.html')
        report = report_template.render(
            date=datetime.datetime.strftime(
                datetime.datetime.now(), '%Y-%m-%d %H:%M:%S'),
            test_results=results
        )
    else:
        report = json.dumps(results)

    outfile.write(report)
    outfile.close()


def main():
    """Main function
    parse arguments
    call tests
    store result
    """

    parser = argparse.ArgumentParser(description='Check OGC WMS servers')
    parser.add_argument('--format', default='html', choices=['json', 'html'],
                        help='Output type, default \'html\'')
    parser.add_argument('--config', type=argparse.FileType('r'),
                        help='''Configuration file ''')
    parser.add_argument('--url', help='Server URL')
    parser.add_argument('--layers', help='List of layers to be checked',
                        nargs='+')
    parser.add_argument('--output', type=argparse.FileType('w'),
                        help='Output file', required=True)

    args = parser.parse_args()

    if not args.config and not args.url:
        sys.exit('''
        ERROR: Either configuration file or url option has to be set

        --config=FILE or --url=http://...
''')

    data = None
    if args.url:
        data = [{
            'url': args.url,
            'layers': args.layers
        }]
    else:
        data = json.load(args.config)
        args.config.close()

    results = test_services(data)
    make_report(args.output, results, args.format)

    general_result = True
    for service in results:
        if not service['passed']:
            general_result = False

    if general_result:
        sys.exit(0)
    else:
        sys.exit('Some tested services may fail. See output file')

if __name__ == '__main__':
    main()
