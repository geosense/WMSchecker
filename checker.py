#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
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
#from tqdm import tqdm
from owslib.wms import WebMapService
from jinja2 import Environment, PackageLoader
import base64
import datetime
import traceback
import sys
import logging
import argparse
from multiprocessing import Pool
import uuid
import sys
import os
import shutil
import time
import sqlite3

FILE = 'urls.json'
OUTPUT = ''
FORMAT_TYPE = ''
DATA_LENGTH = 0

LOG='/tmp/checker.log'
log_file = open(LOG, 'w')
log_file.close()


logging.basicConfig(level=logging.ERROR)


def test_layer(service, name):
    """
    Test given layer name from given WMS service
    """

    result = {}
    is_image = None
    data = None
    if name in service.contents:
        try:
            content = service.contents[name]
            response = service.getmap(
                layers=[name],
                srs=content.boundingBox[-1],
                bbox=content.boundingBox[:-1],
                format='image/png',
                size=[20, 20]
            )
            data = response.read()

            is_image = data[:8].find(b'PNG') > -1

            if is_image:
                data = base64.b64encode(data).decode('utf-8')

        except Exception as e:
            data = traceback.format_exc()
    else:
        data = 'Layer "%s" is not available' % name

    #print(service.url + "?service=wms&request=getmap&layers=" +
    #            name +
    #            "&srs=" + content.boundingBox[-1] +
    #            "&version=1.0.0" +
    #            "&bbox=" + ",".join([str(x) for x in content.boundingBox[:-1]]) +
    #            "&format=image/png" +
    #            "&width=20&height=20")
    result = {
        'is_image': is_image,
        'content': data
    }
    return result


def test_layers(service, inlayers=None):
    """Test layers of given name from given WMS service
    """

    if not inlayers:
        inlayers = []
        for name in service.contents:
            inlayers.append(name)

    layers = {}
    for name in inlayers:
        layers[name] = test_layer(service, name)

    return layers


def test_service(record, output, format_type):
    """Test given service based on configuration record
    dictionary with at least 'url' attribute
    """

    url = record['url']
    # version = '1.3.0'
    # if record.get('version'):
    #    version = record['version']

    log_file = open(LOG, 'a')
    log_file.write(url + "\n")
    log_file.close()

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

        if record.get('use_service_url'):
            method = next((getmap_method for getmap_method in service.getOperationByName('GetMap').methods if getmap_method['type'].lower() == 'get'))
            method['url'] = service.url

        layers = None
        if 'layers' in record:
            layers = record['layers']
        layers = test_layers(service, layers)
        for layer in layers:
            if not layers[layer]['is_image']:
                result = False


    result = {
        'id': str(uuid.uuid4()),
        'url': url,
        'title': title,
        'layers': layers,
        'passed': result,
        'exception': exception
    }

    make_report(output, result, format_type)

    return result

def run_test_service(record):
    return test_service(record, OUTPUT, FORMAT_TYPE)


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

    global OUTPUT

    conn = sqlite3.connect(os.path.join(OUTPUT, 'data.db'))
    conn.execute("""
        CREATE TABLE results (id varchar(255),
                              url varchar (255),
                              title varchar (255),
                              passed boolean)
        """)
    conn.commit()
    conn.close()

    pool = Pool(processes=5)
    results = pool.map(run_test_service, data)
    #results = []
    #for i in data[:10]:
    #    results.append(run_test_service(i))
    return results

def _get_data_fromdb(outdir):

    conn = sqlite3.connect(os.path.join(outdir, 'data.db'))
    out = conn.execute(" SELECT id, url, title, passed from results ")

    data = []
    for record in out.fetchall():
        data.append({
            'id': record[0],
            'url': record[1],
            'title': record[2],
            'passed': record[3] == 'True'
        })
    conn.close()

    return data


def _write_index_json(outdir):

    outfile = os.path.join(outdir, 'index.json')
    data = _get_data_fromdb(outdir)

    outfile_obj = open(outfile, 'w')
    json.dump(data, outfile_obj, indent=4)
    outfile_obj.close()

def _write_index_html(outdir):

    outfile = os.path.join(outdir, 'index.html')
    data = _get_data_fromdb(outdir)

    env = Environment(loader=PackageLoader('wmschecker', 'templates'))
    report_template = env.get_template('index.html')
    number_failed = len(list(filter(lambda service: not service['passed'], data)))
    report = report_template.render(
        date=datetime.datetime.strftime(
            datetime.datetime.now(), '%Y-%m-%d %H:%M:%S'),
        data=data,
        total=len(data),
        number_of_failed = number_failed
    )

    outfile_obj = open(outfile, 'w')
    outfile_obj.write(report)
    outfile_obj.close()


def _write_db(outdir, result, outformat, count=0):
    """Write index file"""

    if count < 10:
        try:
            conn = sqlite3.connect(os.path.join(outdir, 'data.db'))
            conn.execute("""
                INSERT INTO
                    results (id, url, title, passed)
                VALUES
                    ('%(id)s','%(url)s','%(title)s', '%(passed)s')
            """ % result)
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            time.sleep(1)
            count += 1
            _write_db(outdir, result, outformat, count)
    else:
        logging.error('Could not write to database, but passing: ' +
                    '[%(id)s, %(url)s, %(title)s, %(passed)s]' % result)
        pass

def make_report(outdir, result, outformat='html'):
    """Save output report to given outname file
    Default is stdout
    """

    report = None
    if outformat == 'html':
        env = Environment(loader=PackageLoader('wmschecker', 'templates'))
        report_template = env.get_template('report_single.html')
        report = report_template.render(
            date=datetime.datetime.strftime(
                datetime.datetime.now(), '%Y-%m-%d %H:%M:%S'),
            server=result,
            percent=len(result)/DATA_LENGTH
        )
    else:
        report = json.dumps(result)

    outfile = open(os.path.join(outdir, result['id']) + '.' + outformat, 'w')
    outfile.write(report)
    outfile.close()

    _write_db(outdir, result, outformat)
    write_file_output(outformat, outdir)

def write_file_output(outformat, outdir):

    if outformat == 'html':
        _write_index_html(outdir)
    else:
        _write_index_json(outdir)


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
    parser.add_argument('--output', type=str,
                        help='Output directory', required=True)

    args = parser.parse_args()


    if os.path.isdir(args.output):
        shutil.rmtree(args.output)
    os.mkdir(args.output)

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

    global OUTPUT
    global FORMAT_TYPE
    global DATA_LENGTH
    OUTPUT = args.output
    FORMAT_TYPE = args.format
    DATA_LENGTH = len(data)

    ok = test_services(data)
    write_file_output(FORMAT_TYPE, OUTPUT)
    if not ok:
        sys.stderr.write('Some tested services may fail. See output dir %s\n'  % OUTPUT)


if __name__ == '__main__':
    main()
