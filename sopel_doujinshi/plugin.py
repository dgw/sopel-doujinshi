"""
doujinshi.py - Sopel doujinshi info plugin
Copyright 2020 dgw
Licensed under the Eiffel Forum License 2

https://sopel.chat
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from importlib import metadata
import re

from lxml import etree
import requests

from sopel import plugin, tools


ITEM_TEMPLATE = {
    'site': 'unknown',
    'link': '',
    'title': 'Title Unknown',
    'tags': [],
}


def say_result(bot, item):
    if item['link']:
        item['link'] = ' | ' + item['link']
    if item['uploaded']:
        item['uploaded'] = ' | Uploaded: ' + item['uploaded']

    tags = item['tags']
    for tag, value in tags.items():
        tags[tag] = ' | {}: {}'.format(tag.title(), value)
    item['tags'] = ''.join(tags.values())

    bot.say('[{site}] {title}{link}{tags}{uploaded}'.format(**item))


NHENTAI_GALLERY_BASE = 'https://nhentai.net/g/'
NHENTAI_GALLERY_PATTERN = NHENTAI_GALLERY_BASE + r'(\d+)/?'
NHENTAI_GALLERY_TEMPLATE = NHENTAI_GALLERY_BASE + '{id}/'
NHENTAI_ID_PATTERN = r'^\d+$'
NHENTAI_SITENAME = 'nhentai'


PACKAGE_NAME = 'sopel-doujinshi'
PACKAGE_VERSION = None
PACKAGE_METADATA = None
PACKAGE_HOMEPAGE = None

try:
    PACKAGE_METADATA = metadata.metadata(PACKAGE_NAME)
    PACKAGE_VERSION = metadata.version(PACKAGE_NAME)
except metadata.PackageNotFoundError:
    pass

if PACKAGE_METADATA is not None:
    PACKAGE_HOMEPAGE = PACKAGE_METADATA.get('Home-page')
    if not PACKAGE_HOMEPAGE:
        for project_url in PACKAGE_METADATA.get_all('Project-URL') or []:
            label, _, url = project_url.partition(',')
            if label.strip().lower() == 'homepage':
                PACKAGE_HOMEPAGE = url.strip()
                break

_user_agent = PACKAGE_NAME
if PACKAGE_VERSION:
    _user_agent += '/{}'.format(PACKAGE_VERSION)
if PACKAGE_HOMEPAGE:
    _user_agent += ' {}'.format(PACKAGE_HOMEPAGE)

HEADERS = {'User-Agent': _user_agent}


@plugin.url(NHENTAI_GALLERY_PATTERN)
def nhentai_link(bot, trigger, match):
    nhentai_info(bot, trigger, match.group(1))


@plugin.commands('nhentai', 'nh')
def nhentai_info(bot, trigger, id_=None):
    """Fetch information about a gallery on nhentai."""
    link = False
    if not id_:  # commanded
        id_ = trigger.group(3)
        if not id_:  # commanded with no argument
            bot.reply('I need a gallery ID number.')
            return plugin.NOLIMIT
        else:  # make sure we give a link to the gallery when commanded
            link = True
    if not re.match(NHENTAI_ID_PATTERN, id_):
        if link:  # only reply when commanded; fail silently for bad links
            bot.reply("Sorry, '{}' doesn't look like a valid gallery ID.".format(id_))
        return plugin.NOLIMIT


    # Now the real "fun" begins
    url = NHENTAI_GALLERY_TEMPLATE.format(id=id_)
    try:
        r = requests.get(url=url, timeout=(10.0, 4.0), headers=HEADERS)
    except requests.exceptions.ConnectTimeout:
        return bot.say("[{}] Connection timed out.".format(NHENTAI_SITENAME))
    except requests.exceptions.ConnectionError:
        return bot.say("[{}] Couldn't connect to server.".format(NHENTAI_SITENAME))
    except requests.exceptions.ReadTimeout:
        return bot.say("[{}] Server took too long to send data.".format(NHENTAI_SITENAME))
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return bot.say("[{}] Gallery {} doesn't exist.".format(NHENTAI_SITENAME, id_))
        return bot.say("[{}] HTTP error: ".format(NHENTAI_SITENAME) + str(e.response.status_code))

    page = etree.HTML(r.content)

    item = copy.deepcopy(ITEM_TEMPLATE)
    item['site'] = NHENTAI_SITENAME
    if link:
        item['link'] = url

    item['title'] = page.xpath(
        '//div[@id="info"]/h1[contains(concat(" ", normalize-space(@class), " "), " title ")]'
        '/span[contains(concat(" ", normalize-space(@class), " "), " pretty ")]')[0].text
    item['tags'] = {}

    # for some reason, nhentai just marks empty tag containers as "hidden"
    # instead of omitting them from the markup like a sane app would do
    # I figure it's more efficient to exclude them from this XPath expression
    # than waste another call to xpath() later on a useless element
    meta_items = page.xpath(
        '//section[@id="tags"]'
        '/div[contains(concat(" ", normalize-space(@class), " "), " tag-container ")]'
        '[not(contains(concat(" ", normalize-space(@class), " "), " hidden "))]'
    )
    for meta_item in meta_items:
        key = meta_item.text.strip().replace(':', '').lower()
        if key == 'uploaded':
            time = meta_item.xpath('.//time')[0]
            timestamp = time.get('datetime')
            if timestamp[-3] == ':':
                # nhentai includes a : in the datetime offset, which
                # python's datetime library doesn't understand, so it
                # has to be removed manually
                timestamp = timestamp[:-3] + timestamp[-2:]
            timestamp = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f%z')
            item['uploaded'] = tools.time.seconds_to_human(
                datetime.now(timezone.utc) - timestamp)
        elif key in ['artists', 'categories', 'characters', 'languages', 'pages', 'parodies', 'tags']:
            tag_class = 'tagchip'
            if key == 'pages':
                # annoying special case
                tag_class = 'tag'
            tags = meta_item.xpath(
                './span[contains(concat(" ", normalize-space(@class), " "), " tags ")]'
                f'//a[contains(concat(" ", normalize-space(@class), " "), " {tag_class} ")]'
                '//span[contains(concat(" ", normalize-space(@class), " "), " name ")]/text()'
            )
            if tags:
                item['tags'][key] = ', '.join(tags)

    say_result(bot, item)
