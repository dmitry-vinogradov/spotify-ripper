# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import urllib3
from colorama import Fore
from spotify_ripper.utils import *
import os
import time
import spotify
import requests
import csv
import re


class WebAPI(object):

    def __init__(self, args, ripper):
        self.args = args
        self.ripper = ripper
        self.cache = {
            "albums_with_filter": {},
            "artists_on_album": {},
            "genres": {},
            "charts": {},
            "large_coverart": {}
        }

    def cache_result(self, name, uri, result):
        self.cache[name][uri] = result

    def get_cached_result(self, name, uri):
        return self.cache[name].get(uri)

    def request_json(self, url, msg):
        res = self.request_url(url, msg)
        return res.json() if res is not None else res

    def get_token(self):
        print(Fore.GREEN + "Attempting to retrieve new token" +
              " from Spotify Web" + Fore.RESET)
        headers = {
            "Connection": "keep - alive",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3"
        }
        url = "https://open.spotify.com/browse/featured"
        res = requests.get(url, headers=headers, verify=False)
        token = None
        start = res.text.find('"accessToken":"')
        if start > -1:
            start += len('"accessToken":"')
            end = res.text.find('","', start)
            token = res.text[start:end]
            print(Fore.GREEN + "Got new token %s" % token +
                  " from Spotify Web" + Fore.RESET)
        else:
            print(Fore.RED + "Unable to retrieve new token" +
                  " from Spotify Web" + Fore.RESET)
        return token

    def request_url(self, url, msg):
        if hasattr(self.args, 'token') is False:
            token = self.get_token()
            if token is not None:
                setattr(self.args, 'token', token)
                return self.request_url(url, msg)
        print(Fore.GREEN + "Attempting to retrieve " + msg +
              " from Spotify's Web API" + Fore.RESET)
        print(Fore.CYAN + url + Fore.RESET)
        urllib3.disable_warnings()
        headers = {"Authorization": "Bearer %s" % self.args.token} if hasattr(self.args, 'token') else {}
        res = requests.get(url, headers=headers, verify=False)
        if res.status_code == 200:
            return res
        else:
            if res.status_code == 401:
                if hasattr(self.args, 'token'):
                    delattr(self.args, 'token')
                    return self.request_url(url, msg)
            print(Fore.YELLOW + "URL returned non-200 HTTP code: " +
                  str(res.status_code) + Fore.RESET)
        return None

    def api_url(self, url_path):
        return 'https://api.spotify.com/v1/' + url_path

    def charts_url(self, url_path):
        return 'https://spotifycharts.com/' + url_path

    # excludes 'appears on' albums for artist
    def get_albums_with_filter(self, uri):
        args = self.args

        album_type = ('&album_type=' + args.artist_album_type) \
            if args.artist_album_type is not None else ""

        market = ('&market=' + args.artist_album_market) \
            if args.artist_album_market is not None else ""

        def get_albums_json(offset):
            url = self.api_url(
                    'artists/' + uri_tokens[2] +
                    '/albums/?=' + album_type + market +
                    '&limit=50&offset=' + str(offset))
            return self.request_json(url, "albums")

        # check for cached result
        cached_result = self.get_cached_result("albums_with_filter", uri)
        if cached_result is not None:
            return cached_result

        # extract artist id from uri
        uri_tokens = uri.split(':')
        if len(uri_tokens) != 3:
            return []

        # it is possible we won't get all the albums on the first request
        offset = 0
        album_uris = []
        total = None
        while total is None or offset < total:
            try:
                # rate limit if not first request
                if total is None:
                    time.sleep(1.0)
                albums = get_albums_json(offset)
                if albums is None:
                    break

                # extract album URIs
                album_uris += [album['uri'] for album in albums['items']]
                offset = len(album_uris)
                if total is None:
                    total = albums['total']
            except KeyError as e:
                break
        print(str(len(album_uris)) + " albums found")
        self.cache_result("albums_with_filter", uri, album_uris)
        return album_uris

    def get_artists_on_album(self, uri):
        def get_album_json(album_id):
            url = self.api_url('albums/' + album_id)
            return self.request_json(url, "album")

        # check for cached result
        cached_result = self.get_cached_result("artists_on_album", uri)
        if cached_result is not None:
            return cached_result

        # extract album id from uri
        uri_tokens = uri.split(':')
        if len(uri_tokens) != 3:
            return None

        album = get_album_json(uri_tokens[2])
        if album is None:
            return None

        result = [artist['name'] for artist in album['artists']]
        self.cache_result("artists_on_album", uri, result)
        return result

    # genre_type can be "artist" or "album"
    def get_genres(self, genre_type, track):
        def get_genre_json(spotify_id):
            url = self.api_url(genre_type + 's/' + spotify_id)
            return self.request_json(url, "genres")

        # extract album id from uri
        item = track.artists[0] if genre_type == "artist" else track.album
        uri = item.link.uri

        # check for cached result
        cached_result = self.get_cached_result("genres", uri)
        if cached_result is not None:
            return cached_result

        uri_tokens = uri.split(':')
        if len(uri_tokens) != 3:
            return None

        json_obj = get_genre_json(uri_tokens[2])
        if json_obj is None:
            return None

        result = json_obj["genres"]
        self.cache_result("genres", uri, result)
        return result

    # doesn't seem to be officially supported by Spotify
    def get_charts(self, uri):
        def get_chart_tracks(metrics, region, time_window, from_date):
            url = self.charts_url(metrics + "/" + region + "/" + time_window +
                "/" + from_date + "/download")

            res = self.request_url(url, region + " " + metrics + " charts")
            if res is not None:
                csv_items = [enc_str(to_ascii(r)) for r in res.text.split("\n")]
                reader = csv.DictReader(csv_items)
                return ["spotify:track:" + row["URL"].split("/")[-1]
                            for row in reader]
            else:
                return []

        # check for cached result
        cached_result = self.get_cached_result("charts", uri)
        if cached_result is not None:
            return cached_result

        # spotify:charts:metric:region:time_window:date
        uri_tokens = uri.split(':')
        if len(uri_tokens) != 6:
            return None

        # some sanity checking
        valid_metrics = {"regional", "viral"}
        valid_regions = {"us", "gb", "ad", "ar", "at", "au", "be", "bg", "bo",
                         "br", "ca", "ch", "cl", "co", "cr", "cy", "cz", "de",
                         "dk", "do", "ec", "ee", "es", "fi", "fr", "gr", "gt",
                         "hk", "hn", "hu", "id", "ie", "is", "it", "lt", "lu",
                         "lv", "mt", "mx", "my", "ni", "nl", "no", "nz", "pa",
                         "pe", "ph", "pl", "pt", "py", "se", "sg", "sk", "sv",
                         "tr", "tw", "uy", "global"}
        valid_windows = {"daily", "weekly"}

        def sanity_check(val, valid_set):
            if val not in valid_set:
                print(Fore.YELLOW +
                      "Not a valid Spotify charts URI parameter: " +
                      val + Fore.RESET)
                print("Valid parameter options are: [" +
                      ", ".join(valid_set)) + "]"
                return False
            return True

        def sanity_check_date(val):
            if  re.match(r"^\d{4}-\d{2}-\d{2}$", val) is None and \
                    val != "latest":
                print(Fore.YELLOW +
                      "Not a valid Spotify charts URI parameter: " +
                      val + Fore.RESET)
                print("Valid parameter options are: ['latest', a date "
                      "(e.g. 2016-01-21)]")
                return False
            return True

        check_results = sanity_check(uri_tokens[2], valid_metrics) and \
            sanity_check(uri_tokens[3], valid_regions) and \
            sanity_check(uri_tokens[4], valid_windows) and \
            sanity_check_date(uri_tokens[5])
        if not check_results:
            print("Generally, a charts URI follow the pattern "
                  "spotify:charts:metric:region:time_window:date")
            return None

        tracks_obj = get_chart_tracks(uri_tokens[2], uri_tokens[3],
                                      uri_tokens[4], uri_tokens[5])
        charts_obj = {
            "metrics": uri_tokens[2],
            "region": uri_tokens[3],
            "time_window": uri_tokens[4],
            "from_date": uri_tokens[5],
            "tracks": tracks_obj
        }

        self.cache_result("charts", uri, charts_obj)
        return charts_obj


    def get_large_coverart(self, uri):
        def get_track_json(track_id):
            url = self.api_url('tracks/' + track_id)
            return self.request_json(url, "track")

        def get_image_data(url):
            response = self.request_url(url, "cover art")
            return response.content

        # check for cached result
        cached_result = self.get_cached_result("large_coverart", uri)
        if cached_result is not None:
            return get_image_data(cached_result)

        # extract album id from uri
        uri_tokens = uri.split(':')
        if len(uri_tokens) != 3:
            return None

        track = get_track_json(uri_tokens[2])
        if track is None:
            return None

        try:
            images = track['album']['images']
        except KeyError:
            return None

        for image in images:
            if image["width"] >= 600:
                self.cache_result("large_coverart", uri, image["url"])
                return get_image_data(image["url"])

        return None

