#!/usr/bin/python
# -*- coding: utf-8 -*-

# thumbor imaging service
# https://github.com/thumbor/thumbor/wiki

# Licensed under the MIT license:
# http://www.opensource.org/licenses/mit-license
# Copyright (c) 2011 globo.com timehome@corp.globo.com
# Copyright (c) 2016 Wikimedia Foundation

# Video loader, only loads the frame needed from a remote video
# Do not use it as-is with persistent storage of originals,
# otherwise the first frame requested will be stored as the
# original for subsequent requests

import re
import os
from urllib import unquote
from functools import partial
from tempfile import NamedTemporaryFile

from thumbor.loaders import LoaderResult
from tornado.process import Subprocess
from thumbor.utils import logger
from wikimedia_thumbor_base_engine import BaseWikimediaEngine


uri_scheme = 'http://'


def should_run(url):
    unquoted_url = unquote(url)

    if re.search(r'\.(ogv|webm)$', unquoted_url, re.I):
        return True

    return False


def load_sync(context, url, callback):
    # Disable storage of original. These lines are useful if
    # you want your Thumbor instance to store all originals persistently
    # except video frames.
    #
    # from thumbor.storages.no_storage import Storage as NoStorage
    # context.modules.storage = NoStorage(context)

    unquoted_url = unquote(url)

    command = BaseWikimediaEngine.wrap_command([
        context.config.FFPROBE_PATH,
        '-v',
        'error',
        '-show_entries',
        'format=duration',
        '-of',
        'default=noprint_wrappers=1:nokey=1',
        '%s%s' % (uri_scheme, unquoted_url)
    ], context)

    logger.debug('Command: %r' % command)

    process = Subprocess(command, stdout=Subprocess.STREAM)
    process.set_exit_callback(
        partial(
            _parse_time_status,
            context,
            unquoted_url,
            callback,
            process
        )
    )


def _parse_time_status(context, url, callback, process, status):
    if status != 0:
        result = LoaderResult()
        result.successful = False
        callback(result)
    else:
        process.stdout.read_until_close(
            partial(
                _parse_time,
                context,
                url,
                callback
            )
        )


def _parse_time(context, url, callback, output):
    duration = float(output)
    unquoted_url = unquote(url)

    try:
        seek = int(context.request.page)
    except AttributeError:
        seek = duration / 2

    destination = NamedTemporaryFile(delete=False)

    command = BaseWikimediaEngine.wrap_command([
        context.config.FFMPEG_PATH,
        # Order is important, for fast seeking -ss has to come before -i
        # As explained on https://trac.ffmpeg.org/wiki/Seeking
        '-ss',
        '%d' % seek,
        '-i',
        '%s%s' % (uri_scheme, unquoted_url),
        '-y',
        '-vframes',
        '1',
        '-an',
        '-f',
        'image2',
        '-nostats',
        '-loglevel',
        'error',
        destination.name
    ], context)

    logger.debug('Command: %r' % command)

    process = Subprocess(command)
    process.set_exit_callback(
        partial(
            _process_output,
            callback,
            destination.name
        )
    )


def _process_output(callback, destination_name, status):
    result = LoaderResult()

    if status != 0:
        result.successful = False
    else:
        result.successful = True
        with open(destination_name, 'rb') as f:
            result.buffer = f.read()
        os.remove(destination_name)

    callback(result)
