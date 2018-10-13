#!/usr/bin/python
import logging
import argparse
import hashlib
import json
import pickle
import os.path
import shutil
import subprocess
from urllib.parse import unquote

import xml.etree.ElementTree as ET

import spotipy
import spotipy.util as util
import pyqrcode
import soco

# Set up logfile
LOG_FORMAT = '%(levelname)s %(asctime)s - %(message)s'
logging.basicConfig(  # filename = 'qrgen.log',
    # filemode = 'w',
    level=logging.INFO,
    format=LOG_FORMAT)
logger = logging.getLogger()

# Build a map of the known commands
commands = json.load(open('command_cards.txt'))

# Load defaults from my_defaults.txt
current_path = os.getcwd()
defaults = json.load(open('my_defaults.txt', 'r'))
default_room = defaults['default_room']
default_spotify_user = defaults['default_spotify_user']
# set spotify authentication variables
sp_client_id = defaults['SPOTIPY_CLIENT_ID']
sp_client_secret = defaults['SPOTIPY_CLIENT_SECRET']
sp_redirect = defaults['SPOTIPY_REDIRECT_URI']
logging.info('Imported defaults: %s' % defaults)

# Parse the command line arguments
arg_parser = argparse.ArgumentParser(
    description='Generates an HTML page containing cards with embedded QR codes that can be interpreted by `qrplay`.')
arg_parser.add_argument('--input', help='the file containing the list of albums, playlists, and tracks to generate')
arg_parser.add_argument('--generate-images', action='store_true',
                        help='generate out/index.html with cards for all items listed in input file')
arg_parser.add_argument('--list-library-albums', action='store_true', help='list all available library albums')
arg_parser.add_argument('--list-library-playlists', action='store_true', help='list all available library playlists')
arg_parser.add_argument('--list-library-tracks', const='all', action='store', nargs='?',
                        help='list all library tracks matching given search term')
arg_parser.add_argument('--spotify-username', default=default_spotify_user,
                        help='the username used to set up Spotify access '
                             '(only needed if you want to generate cards for Spotify tracks)')
arg_parser.add_argument('--zones', action='store_true',
                        help='generate out/zones.html with cards for all available Sonos zones')
arg_parser.add_argument('--commands', action='store_true',
                        help='generate out/commands.html with cards for all commands defined in command_cards.txt')
arg_parser.add_argument('--set-defaults', action='store_true', help='set defaults to be written to my_defaults.txt')
args = arg_parser.parse_args()
logging.info('Arguments: %s' % args)

# set filenames for pickle of hashed library items
hashed_tracks = 'hashed_tracks.dat'
hashed_albums = 'hashed_albums.dat'

if args.spotify_username:
    # Set up Spotify access
    scope = 'user-library-read'
    token = util.prompt_for_user_token(args.spotify_username, scope, client_id=sp_client_id,
                                       client_secret=sp_client_secret, redirect_uri=sp_redirect)
    if token:
        sp = spotipy.Spotify(auth=token)
    else:
        raise ValueError('Can\'t get Spotify token for ' + username)
else:
    # No Spotify
    sp = None


def set_defaults():
    # collect items to use with qrplay: spotify username, default sonos zone
    defaults = {}
    defaults.update({'default_spotify_user': input('Spotify username: ')})
    sonos_zones = []
    for zone in list(soco.discover()):
        sonos_zones.append(zone)
        logging.info('Zone found: %s' % (zone.player_name))
    defaults.update({'default_room': input('Default Sonos zone/room: ')})
    current_path = os.getcwd()
    output_file_defaults = os.path.join(current_path, 'my_defaults.txt')
    file = open(output_file_defaults, 'w')
    json.dump(defaults, file, indent=2)
    file.close()


def get_zones():
    # create a list with all available zones
    sonos_zones = []
    for zone in list(soco.discover()):
        sonos_zones.append(zone)
    logging.info('List of zones: %s' % (sonos_zones))

    # copy cards.css to /out folder
    shutil.copyfile('cards.css', 'out/cards.css')
    shutil.copyfile('sonos_360.png', 'out/sonos_360.png')

    # begin the HTML template
    html = '''
        <html>
        <head>
        <link rel="stylesheet" href="cards.css"
        </head>
        <body>
        '''

    for n in sonos_zones:
        qrout = 'out/' + n.player_name + '_qr.png'
        artout = 'out/' + n.player_name + '_art.png'
        qrimg = n.player_name + '_qr.png'
        artimg = n.player_name + '_art.png'
        qr = pyqrcode.create('changezone:' + n.player_name)
        qr.png(qrout, scale=6)
        # qr.show()
        # generate html
        html += '<div class="card">\n'
        html += '  <img src="sonos_360.png" class="art"/>\n'.format(artout)
        html += '  <img src="' + qrimg + '" class="qrcode"/>\n'.format(qrout)
        html += '  <div class="labels">\n'
        html += '    <p class="zone">' + n.player_name + '</p>\n'
        html += '  </div>\n'
        html += '</div>\n'

    html += '</body>\n'
    html += '</html>\n'

    with open('out/zones.html', 'w') as f:
        f.write(html)


def list_library_playlists():
    logging.info('Getting sonos and library playlists')
    # Get sonos playlists
    result1 = soco.music_library.MusicLibrary().get_music_library_information('sonos_playlists', complete_result=True)
    # Get imported playlists, append to list of sonos playlists
    result2 = soco.music_library.MusicLibrary().get_playlists(complete_result=True)
    result = result1 + result2
    with open('out/all_playlists.txt', 'w') as f:
        for playlist in result:
            didl = soco.data_structures.to_didl_string(playlist)
            xmltree = ET.ElementTree(ET.fromstring(didl))
            xmltree = xmltree.getroot()
            xmlTitle = xmltree[0][0].text
            xmlURI = xmltree[0][1].text
            f.write('pl:{}${}\n'.format(xmlURI, xmlTitle))
    return


def list_library_albums():
    logging.info('Getting library albums')
    result = soco.music_library.MusicLibrary().get_albums(complete_result=True)
    with open('out/all_albums.txt', 'w') as f:
        for i, album in enumerate(result):
            logging.info('%s %s %s' % (album.creator, album.title, album.item_id))
            didl = soco.data_structures.to_didl_string(album)
            # construct string of album metadata for later encoding
            xmltree = ET.ElementTree(ET.fromstring(didl))
            xmltree = xmltree.getroot()
            xmlURI = xmltree[0][1].text
            xmlID = xmlURI.split('#')[1]
            xmlArtist = xmltree[0][2].text
            xmlTitle = xmltree[0][0].text
            xmlArtUrl = xmltree[0][3].text
            # write uuid of sonos zone speaker for later use in playback of albums
            if i == 0:
                xmlprefix = xmlURI.split('#')[0]
                f.write('album_uuid_prefix: {}\n'.format(xmlprefix))
            f.write('alb:{}${}${}${}\n'.format(xmlID, xmlArtist, xmlTitle, xmlArtUrl))
    return


def list_library_tracks():
    if args.list_library_tracks == 'all':
        logging.info('Getting all library tracks.')
        term = None
    else:
        term = args.list_library_tracks
        logging.info('Getting all library trackst that match search term \'%s\'.' % (args.list_library_tracks))
    result = soco.music_library.MusicLibrary().get_tracks(search_term=term, complete_result=True)
    with open('out/all_tracks.txt', 'w') as f:
        for track in result:
            didl = soco.data_structures.to_didl_string(track)
            xmltree = ET.ElementTree(ET.fromstring(didl))
            xmltree = xmltree.getroot()
            xmlURI = xmltree[0][1].text
            xmlArtist = xmltree[0][2].text
            xmlTitle = xmltree[0][0].text
            xmlAlbum = xmltree[0][4].text
            xmlArtUrl = xmltree[0][3].text
            f.write('trk:{}${}${}${}${}\n'.format(xmlURI, xmlArtist, xmlTitle, xmlAlbum, xmlArtUrl))


# Removes extra junk from titles, e.g:
#   (Original Motion Picture Soundtrack)
#   - From <Movie>
#   (Remastered & Expanded Edition)
def strip_title_junk(title):
    junk = [' (Original', ' - From', ' (Remaster', ' [Remaster']
    for j in junk:
        index = title.find(j)
        if index >= 0:
            return title[:index]
    return title


def process_command(uri, index):
    cmdname = commands[uri]['label']
    arturl = commands[uri]['image']

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    # Create a QR code from the command URI
    qr1 = pyqrcode.create(uri)
    qr1.png(qrout, scale=6)
    # qr1.show()

    if 'http' in arturl:
        logging.info(subprocess.check_output(['curl', arturl, '-o', artout]))
    else:
        shutil.copyfile(arturl, artout)
    return cmdname, None, None


def process_spotify_track(uri, index):
    if not sp:
        raise ValueError('Must configure Spotify API access first using `--spotify-username`')

    track = sp.track(uri)

    logging.info(track)
    logging.info('track    : %s' % (track['name']))

    # strip title junk
    song = strip_title_junk(track['name'])
    artist = strip_title_junk(track['artists'][0]['name'])
    album = strip_title_junk(track['album']['name'])
    arturl = track['album']['images'][0]['url']

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    # Create a QR code from the track URI
    qr1 = pyqrcode.create(uri)
    qr1.png(qrout, scale=6)
    # qr1.show()

    # Fetch the artwork and save to the output directory
    logging.info(subprocess.check_output(['curl', arturl, '-o', artout]))

    return song, album, artist


def process_spotify_album(uri, index):
    if not sp:
        raise ValueError('Must configure Spotify API access first using `--spotify-username`')

    album = sp.album(uri)

    logging.info(album['name'])

    # strip title junk
    album_name = strip_title_junk(album['name'])
    artist_name = strip_title_junk(album['artists'][0]['name'])
    arturl = album['images'][0]['url']

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    # Create a QR code from the album URI
    qr1 = pyqrcode.create(uri)
    qr1.png(qrout, scale=6)
    # qr1.show()

    # Fetch the artwork and save to the output directory
    logging.info(subprocess.check_output(['curl', arturl, '-o', artout]))

    album_blank = ''
    return album_name, album_blank, artist_name


def process_spotify_playlist(uri, index):
    if not sp:
        raise ValueError('Must configure Spotify API access first using `--spotify-username`')

    sp_user = uri.split(':')[2]
    playlist = sp.user_playlist(sp_user, uri)
    playlist_name = playlist['name']

    logging.info(playlist['name'])

    # strip title junk
    playlist_owner = strip_title_junk(playlist['owner']['id'])
    arturl = playlist['images'][0]['url']

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    # Create a QR code from the playlist URI
    qr1 = pyqrcode.create(uri)
    qr1.png(qrout, scale=6)
    # qr1.show()

    # Fetch the artwork and save to the output directory
    logging.info(subprocess.check_output(['curl', arturl, '-o', artout]))

    playlist_blank = ''
    return playlist_name, playlist_owner, playlist_blank


def process_library_playlist(uri, index):
    # library playlist looks like:
    #   pl:file:///jffs/settings/savedqueues.rsq#0$Ray Charles et. al.
    # card needs: playlist title, uri

    xlist = uri.split('$')
    x_uri = xlist[0]
    x_title = xlist[1]
    song = ''
    artist = ''
    album = strip_title_junk(x_title)

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    # Create a QR code from the playlist URI
    qr1 = pyqrcode.create(x_uri)
    qr1.png(qrout, scale=6)
    # qr1.show()

    # Set default playlist art
    shutil.copyfile('ic_playlist_play_black_48dp.png', artout)

    return song, album, artist


def process_library_album(uri, index):
    global default_room
    # library album looks like:
    #   alb:A:ALBUM/Wolfgang%20Amadeus%20Phoenix$Phoenix$Wolfgang Amadeus Phoenix$/getaa?u=x-file-cifs%3a%2f%2fcomputer%2fmusic%2fiTunes%2fMusic%2fPhoenix%2fWolfgang%2520Amadeus%2520Phoenix%2f01%2520Lisztomania.mp3&v=158
    # library album to be hashed looks like:
    #   alb:hsh:A:ALBUM/Wolfgang%20Amadeus%20Phoenix$Phoenix$Wolfgang Amadeus Phoenix$/getaa?u=x-file-cifs%3a%2f%2fcomputer%2fmusic%2fiTunes%2fMusic%2fPhoenix%2fWolfgang%2520Amadeus%2520Phoenix%2f01%2520Lisztomania.mp3&v=158
    # card needs: uri, album title, album artist, album art
    xlist = uri.split('$')
    x_uri = xlist[0]
    x_artist = xlist[1]
    x_title = xlist[2]
    x_art_url = xlist[3]

    song = ''
    artist = strip_title_junk(x_artist)
    album = strip_title_junk(x_title)
    # build full album art URI by directly accessing helper method in soco core
    spkr = soco.discovery.by_name(default_room)
    arturl = spkr.music_library.build_album_art_full_uri(x_art_url)

    # Fix any missing 'The' prefix
    # Sonos strips the "The" prefix for bands that start with "The"
    # (it appears to do this only in listing contexts; when querying the
    # current/next queue track it still includes the "The").
    # As a dumb hack (to preserve the "The") we can look at the raw URI
    # for the track artwork (this assumes an iTunes-style directory structure),
    # parse out the artist directory name and see if it starts with "The".
    uri_path = unquote(x_art_url)
    lib_part = uri_path.split('/iTunes/Music/', 1)[-1]
    artist_part = lib_part.split('/', 1)[0]
    if artist_part.startswith('The%20'):
        artist = 'The ' + artist

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    if 'hsh:' in x_uri:
        # Create a hash string for simpler QR code
        URItohash = x_uri[8:]
        hash_object = hashlib.md5(URItohash.encode())
        albhash = 'alb:hsh:' + hash_object.hexdigest()
        # Write hash and track uri to pickle so qrplay can retrieve it later
        d = {}
        if os.path.exists(hashed_albums):
            with open(hashed_albums, 'rb') as r:
                d = pickle.load(r)
        if albhash not in d:
            d[albhash] = URItohash
        with open(hashed_albums, 'wb') as w:
            pickle.dump(d, w)
        # Create a QR code from the hashed album URI
        qr1 = pyqrcode.create(albhash)
    else:
        # Create a QR code from the album URI
        qr1 = pyqrcode.create(x_uri)

    # Write the QR code to disk
    qr1.png(qrout, scale=6)
    # qr1.show()

    # Fetch the artwork and save to the output directory.
    # Some itunes artwork is too large to display in sonos, and in those cases,
    # this fetch will fail partway through. Current workaround is to use generic
    # graphic in such cases.
    try:
        logging.info(subprocess.check_output(['curl', arturl, '-o', artout]))
    except subprocess.CalledProcessError as e:
        logging.info('Got error from curl, setting album art to default.')
        shutil.copyfile('ic_album_black_48dp.png', artout)

    # check if we have an empty artwork file. If so, set to default
    if os.path.getsize(artout) == 0:
        shutil.copyfile('ic_album_black_48dp.png', artout)

    return song, album, artist


def process_library_track(uri, index):
    global default_room
    # library track looks like:
    #   trk:x-file-cifs://computer/music/iTunes/Music/Original%20Soundtrack/Chants%20From%20The%20Thin%20Red%20Line/01%20Jisas%20Yu%20Hand%20Blong%20Mi.mp3$Choir of All Saints$Jisas Yu Hand Blong Mi$Chants From The Thin Red Line$/getaa?u=x-file-cifs%3a%2f%2fcomputer%2fmusic%2fiTunes%2fMusic%2fOriginal%2520Soundtrack%2fChants%2520From%2520The%2520Thin%2520Red%2520Line%2f01%2520Jisas%2520Yu%2520Hand%2520Blong%2520Mi.mp3&v=158
    # card needs: uri, track title, track artist, album title, album art

    xlist = uri.split('$')
    fullURI = xlist[0]
    xURI = fullURI[4:]
    xArtist = xlist[1]
    xTitle = xlist[2]
    xAlbum = xlist[3]
    xArtUrl = xlist[4]

    song = strip_title_junk(xTitle)
    artist = strip_title_junk(xArtist)
    album = strip_title_junk(xAlbum)
    # build full album art URI by directly accessing helper method in soco core
    spkr = soco.discovery.by_name(default_room)
    arturl = spkr.music_library.build_album_art_full_uri(xArtUrl)

    # Fix any missing 'The' prefix
    # Sonos strips the "The" prefix for bands that start with "The"
    # (it appears to do this only in listing contexts; when querying the
    # current/next queue track it still includes the "The").
    # As a dumb hack (to preserve the "The") we can look at the raw URI
    # for the track artwork (this assumes an iTunes-style directory structure),
    # parse out the artist directory name and see if it starts with "The".
    uri_path = unquote(xArtUrl)
    lib_part = uri_path.split('/iTunes/Music/', 1)[-1]
    artist_part = lib_part.split('/', 1)[0]
    if artist_part.startswith('The%20'):
        artist = 'The ' + artist

    # Determine the output image file names
    qrout = 'out/{0}qr.png'.format(index)
    artout = 'out/{0}art.jpg'.format(index)

    # Create a hash string for simpler QR code
    hash_object = hashlib.md5(xURI.encode())
    trkhash = 'trk:' + hash_object.hexdigest()
    # Write hash and track uri to pickle so qrplay can retrieve it later
    d = {}
    if os.path.exists(hashed_tracks):
        with open(hashed_tracks, 'rb') as r:
            d = pickle.load(r)
    if trkhash not in d:
        d[trkhash] = xURI
    with open(hashed_tracks, 'wb') as w:
        pickle.dump(d, w)

    # Create a QR code from the track URI
    qr1 = pyqrcode.create(trkhash)
    qr1.png(qrout, scale=6)
    # qr1.show()

    # Fetch the artwork and save to the output directory
    try:
        logging.info(subprocess.check_output(['curl', arturl, '-o', artout]))
    except subprocess.CalledProcessError as e:
        logging.info('Got error from curl, setting track art to default.')
        shutil.copyfile('ic_album_black_48dp.png', artout)

    # check if we have an empty artwork file. If so, set to default
    if os.path.getsize(artout) == 0:
        shutil.copyfile('ic_album_black_48dp.png', artout)

    return song, album, artist


# Return the HTML content for a single card.
def card_content_html(index, artist, album, song):
    qrimg = '{0}qr.png'.format(index)
    artimg = '{0}art.jpg'.format(index)

    html = ''
    html += '  <img src="{0}" class="art"/>\n'.format(artimg)
    html += '  <img src="{0}" class="qrcode"/>\n'.format(qrimg)
    html += '  <div class="labels">\n'
    if song:
        html += '    <p class="song">{0}</p>\n'.format(song)
    else:
        html += '    <p class="song">{0}</p>\n'.format(album)
    if artist:
        html += '    <p class="artist"><span class="small">par</span> {0}</p>\n'.format(artist)
    if album and song:
        html += '    <p class="album"><span class="small">de</span> {0}</p>\n'.format(album)
    html += '  </div>\n'
    return html


# Generate a PNG version of an individual card (with no dashed lines).
# (PNG conversion disabled by dernorberto)
def generate_individual_card_image(index, artist, album, song):
    # First generate an HTML file containing the individual card
    html = ''
    html += '<html>\n'
    html += '<head>\n'
    html += ' <link rel="stylesheet" href="cards.css">\n'
    html += '</head>\n'
    html += '<body>\n'

    html += '<div class="singlecard">\n'
    html += card_content_html(index, artist, album, song)
    html += '</div>\n'

    html += '</body>\n'
    html += '</html>\n'

    html_filename = 'out/{0}.html'.format(index)
    with open(html_filename, 'w') as f:
        f.write(html)

    # Then convert the HTML to a PNG image (beware the hardcoded values; these need to align
    # with the dimensions in `cards.css`)
    ## (disabled conversion of HTML to PNG)
    # png_filename = 'out/{0}'.format(index)
    # logging.info(subprocess.check_output(['webkit2png', html_filename, '--scale=1.0', '--clipped', '--clipwidth=720', '--clipheight=640', '-o', png_filename]))

    # Rename the file to remove the extra `-clipped` suffix that `webkit2png` includes by default
    # os.rename(png_filename + '-clipped.png', png_filename + 'card.png')


def generate_cards():
    # Create the output directory
    dirname = os.getcwd()
    outdir = os.path.join(dirname, 'out')
    if not os.path.exists(outdir):
        os.mkdir(outdir)

    # Read the file containing the list of commands and songs to generate
    if args.input:
        with open(args.input) as f:
            lines = f.readlines()
    elif args.commands:
        lines = []
        for command in commands:
            lines.append(commands[command]['command'])

    # The index of the current item being processed
    index = 0

    # Copy the CSS file into the output directory.  (Note the use of 'page-break-inside: avoid'
    # in `cards.css`; this prevents the card divs from being spread across multiple pages
    # when printed.)
    shutil.copyfile('cards.css', 'out/cards.css')

    # Begin the HTML template
    html = '''
        <html>
        <head>
        <meta charset="UTF-8">
        <link rel="stylesheet" href="cards.css">
        </head>
        <body>
        '''

    for line in lines:
        # Trim newline
        line = line.strip()

        # Remove any trailing comments and newline (and ignore any empty or comment-only lines)
        # line = line.split('#')[0]
        # line = line.strip()
        # if not line:
        #    continue

        if line.startswith('cmd:'):
            (song, album, artist) = process_command(line, index)
        elif line.startswith('mode:'):
            (song, album, artist) = process_command(line, index)
        elif line.startswith('spotify:album:'):
            (song, album, artist) = process_spotify_album(line, index)
        elif line.startswith('spotify:track:'):
            (song, album, artist) = process_spotify_track(line, index)
        elif line.startswith('spotify:user:'):
            if (':playlist:') in line:
                (song, album, artist) = process_spotify_playlist(line, index)
        elif line.startswith('trk:'):
            (song, album, artist) = process_library_track(line, index)
        elif line.startswith('alb:'):
            (song, album, artist) = process_library_album(line, index)
        elif line.startswith('pl:'):
            (song, album, artist) = process_library_playlist(line, index)
        else:
            print('Failed to handle URI: ' + line)
            exit(1)

        # Append the HTML for this card
        if album == '':
            html += '<div class="card">\n'
            html += card_content_html(index, artist, album, song)
            html += '</div>\n'
        else:
            html += '<div class="card">\n'
            html += card_content_html(index, artist, album, song)
            html += '</div>\n'

        if args.generate_images:
            # Also generate an individual PNG for the card
            generate_individual_card_image(index, artist, album, song)

        if args.zones:
            generate_individual_card_image(index, artist, album, song)

        if index % 2 == 1:
            html += '<br style="clear: both;"/>\n'

        index += 1

    html += '</body>\n'
    html += '</html>\n'

    if args.commands:
        with open('out/commands.html', 'w') as f:
            f.write(html)
    else:
        with open('out/index.html', 'w') as f:
            f.write(html)


if args.input:
    generate_cards()
elif args.list_library_albums:
    list_library_albums()
elif args.list_library_playlists:
    list_library_playlists()
elif args.list_library_tracks:
    list_library_tracks()
elif args.zones:
    get_zones()
elif args.commands:
    generate_cards()
elif args.set_defaults:
    set_defaults()
