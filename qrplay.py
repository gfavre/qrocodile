#!/usr/bin/python

import logging
import argparse
import json
import os
import pickle
import subprocess
import sys
from time import sleep
import RPi.GPIO as GPIO
import spotipy
import spotipy.util as util
import soco
from soco.data_structures import DidlItem, DidlResource

# Set up logfile
LOG_FORMAT = '%(levelname)s %(asctime)s - %(message)s'
logging.basicConfig(#filename = 'qrplay.log',
                    #filemode = 'w',
                    level = logging.INFO,
                    format = LOG_FORMAT)
logger = logging.getLogger()

# check python version
if sys.version_info[0] < 3:
    raise Exception("Python 3 or a more recent version is required.")

# set up GPIO for wired LED
GPIO.setmode(GPIO.BOARD)
GPIO.setup(7, GPIO.OUT)
# make sure it's turned on
GPIO.output(7,True)

# load defaults from my_defaults.txt
current_path = os.getcwd()
defaults = json.load(open('my_defaults.txt','r'))
default_room = defaults['default_room']
default_spotify_user = defaults['default_spotify_user']
# set spotify authentication variables
sp_client_id = defaults['SPOTIPY_CLIENT_ID']
sp_client_secret = defaults['SPOTIPY_CLIENT_SECRET']
sp_redirect = defaults['SPOTIPY_REDIRECT_URI']
# set player uuid for use in building album URIs
album_prefix = defaults['album_uuid_prefix']
logger.info('Imported defaults: %s' % (defaults))

# Parse the command line arguments
arg_parser = argparse.ArgumentParser(description='Translates QR codes detected by a camera into Sonos commands.')
arg_parser.add_argument('--default-device', default=default_room, help='the name of your default device/room')
arg_parser.add_argument('--linein-source', default='Living Room', help='the name of the device/room used as the line-in source')
arg_parser.add_argument('--debug-file', help='read commands from a file instead of launching scanner')
arg_parser.add_argument('--spotify-username', default=default_spotify_user, help='the username used to setup Spotify access(only needed if you want to use cards for Spotify tracks)')
args = arg_parser.parse_args()

# set filename for pickle of hashed library items
hashed_tracks = 'hashed_tracks.dat'
hashed_albums = 'hashed_albums.dat'

# UNUSED until SoCo restores support for spotify
if args.spotify_username:
    # Set up Spotify access
    scope = 'user-library-read'
    token = util.prompt_for_user_token(args.spotify_username,scope,client_id=sp_client_id,client_secret=sp_client_secret,redirect_uri=sp_redirect)
    if token:
        sp = spotipy.Spotify(auth=token)
        logger.info("logged into Spotify")
    else:
        raise ValueError('Can\'t get Spotify token for ' + username)
        logger.info('Can\'t get Spotify token for ' + username)
else:
    # No Spotify
    sp = None
    logger.info('Not using a Spotify account')

# Load the most recently used device, if available, otherwise fall back on the `default-device` argument
try:
    with open('.last-device', 'r') as device_file:
        current_device = device_file.read().replace('\n', '')
        logger.info('Defaulting to last used room: ' + current_device)
except:
    current_device = defaults['default_room']
    current_device = args.default_device
    logger.info('Initial room: ' + current_device)

# set soco instance for accessing sonos speaker
spkr = soco.discovery.by_name(current_device).group.coordinator

# Keep track of the last-seen code
last_qrcode = ''

class Mode:
    PLAY_SONG_IMMEDIATELY = 1
    PLAY_ALBUM_IMMEDIATELY = 2
    BUILD_QUEUE = 3

current_mode = Mode.PLAY_ALBUM_IMMEDIATELY

def switch_to_room(room):
    global spkr

    if spkr.player_name != room:
        spkr = soco.discovery.by_name(room)
    current_device = spkr.player_name
    with open(".last-device", "w") as device_file:
        device_file.write(current_device)

# Causes the onboard green LED to blink on and off twice.  (This assumes Raspberry Pi 3 Model B; your
# mileage may vary.)
def blink_led():
    duration = 0.15

    def led_off():
        subprocess.call("echo 0 > /sys/class/leds/led0/brightness", shell=True)
        GPIO.output(7,False)

    def led_on():
        subprocess.call("echo 1 > /sys/class/leds/led0/brightness", shell=True)
        GPIO.output(7,True)

    # Technically we only need to do this once when the script launches
    subprocess.call("echo none > /sys/class/leds/led0/trigger", shell=True)

    led_on()
    sleep(duration)
    led_off()
    sleep(duration)
    led_on()
    sleep(duration)
    led_off()

    # we need the GPIO LED to stay on because it illuminates the cards for the camera
    GPIO.output(7,True)

def handle_command(qrcode):
    global current_mode
    global spkr

    logger.info('HANDLING COMMAND: ' + qrcode)

    if qrcode == 'cmd:turntable':
        spkr.switch_to_line_in(source=args.linein_source)
        spkr.play()
    elif qrcode.startswith('changezone:'):
        newroom = qrcode.split(":")[1]
        logger.info('Switching to '+ newroom)
        switch_to_room(newroom)
    elif qrcode.startswith('cmd:'):
        action = qrcode.split(":")[1]
        if action == 'play':
            spkr.play()
        elif action == 'pause':
            spkr.pause()
        elif action == 'next':
            spkr.next()
        elif action == 'prev':
            spkr.previous()
        elif action == 'stop':
            spkr.stop()
        elif action == 'shuffle/on':
            spkr.play_mode = 'SHUFFLE_NOREPEAT'
        elif action == 'shuffle/off':
            spkr.play_mode = 'NORMAL'
    elif qrcode == 'mode:songonly':
        current_mode = Mode.PLAY_SONG_IMMEDIATELY
    elif qrcode == 'mode:wholealbum':
        current_mode = Mode.PLAY_ALBUM_IMMEDIATELY
    elif qrcode == 'mode:buildqueue':
        current_mode = Mode.BUILD_QUEUE
        spkr.pause()
        spkr.clear_queue()
    else:
        logger.info('No recognized command in handle_command.')


def handle_library_item(uri):
    global spkr
    global album_prefix

    logger.info('PLAYING FROM LIBRARY: ' + uri)
    # TODO: re-implement queue-building as in chrispcampbell original
    ############
    #
    # Playing albums
    #
    #############

    # to playback, construct a dummy DidlMusicAlbum to send to sonos queue
    # needed to play album: URI, and album_id
    # all albums share URI, which is:
    # x-rincon-playlist:RINCON_[uuid of sonos zone]
    # album_id can be got from QR code. It looks like:
    # alb:A:ALBUM/Bone%20Machine
    # albums can also be hashed. they look like:
    # alb:hsh:[hashed_id]
    
    if 'alb:' in uri:
        # if this is a 'hashed' album, get album id from hashed resource
        if 'hsh:' in uri:
            with open(hashed_albums, 'rb') as r:
                b = pickle.loads(r.read())
            album_id = b[uri]
        else:
            album_id = uri[4:]
        album_fullURI = album_prefix + '#' + album_id
        logging.info('sending full uri %s' % (album_fullURI))

        # SoCo needs a DidlResource object to play albums
        # We can construct a 'dummy' DidlResource with generic metadata,
        # and when this is passed to the speaker, SoCo/Sonos will be able to fetch
        # the album from the music library.
        res = [DidlResource(uri=album_fullURI, protocol_info='dummy')]
        didl = soco.data_structures.DidlMusicAlbum(title='dummy',parent_id='dummy',item_id=album_id,resources=res)
        spkr.clear_queue()
        spkr.add_to_queue(didl)
        spkr.play()

    ########
    #
    # Playing playlists or tracks
    #
    #########

    # to playback, you need only the URI of the playlist/track,
    # which comes in one of two forms.
    # Sonos playlist looks like:
    # file:///jffs/settings/savedqueues.rsq#0
    # Imported itunes playlist looks like:
    # x-file-cifs://computer/music/iTunes/iTunes%20Music%20Library.xml#9D1D3FDCFDBB6751
    # Track looks like:
    # x-file-cifs://computer/music/iTunes/Music/Original%20Soundtrack/Chants%20From%20The%20Thin%20Red%20Line/01%20Jisas%20Yu%20Hand%20Blong%20Mi.mp3

    elif 'pl:' in uri:
        pluri = uri[3:]
        spkr.clear_queue()
        spkr.add_uri_to_queue(uri=pluri)
        spkr.play()
    elif 'trk:' in uri:
        # look up hashuri in hashed tracks
        with open(hashed_tracks, 'rb') as r:
            b = pickle.loads(r.read())
        trkuri = b[uri]
        spkr.clear_queue()
        spkr.add_uri_to_queue(uri=trkuri)
        spkr.play()


# UNUSED until SoCo restores support for spotify
def handle_spotify_item(uri):
    logger.info('PLAYING FROM SPOTIFY: ' + uri)

    if current_mode == Mode.BUILD_QUEUE:
        action = 'queue'
    elif current_mode == Mode.PLAY_ALBUM_IMMEDIATELY:
        action = 'clearqueueandplayalbum'
    else:
        action = 'clearqueueandplaysong'

    perform_room_request('spotify/{0}/{1}'.format(action, uri))

# UNUSED until SoCo restores support for spotify
def handle_spotify_album(uri):
    logger.info('PLAYING ALBUM FROM SPOTIFY: ' + uri)

    album_raw = sp.album(uri)
    album_name = album_raw['name']
    artist_name = album_raw['artists'][0]['name']

    # create and update the track list
    album_tracks_raw = sp.album_tracks(uri,limit=50,offset=0)
    album_tracks = {}

    # clear the sonos queue
    action = 'clearqueue'
    perform_room_request('{0}'.format(action))

    # turn off shuffle before starting the new queue
    action = 'shuffle/off'
    perform_room_request('{0}'.format(action))

    for tack in album_tracks_raw['items']:
        track_number = track['track_number']
        track_name = track['name']
        track_uri = track['uri']
        album_tracks.update({track_number: {}})
        album_tracks[track_number].update({'uri': track_uri})
        album_tracks[track_number].update({'name': track_name})
        logger.info(track_number)
        if track_number == int('1'):
            # play track 1 immediately
            action = 'now'
            perform_room_request('spotify/{0}/{1}'.format(action, str(track_uri)))
        else:
            # add all remaining tracks to queue
            action = 'queue'
            perform_room_request('spotify/{0}/{1}'.format(action, str(track_uri)))

# UNUSED until SoCo restores support for spotify
def handle_spotify_playlist(uri):
    
    logger.info('PLAYING PLAYLIST FROM SPOTIFY: ' + uri)
    sp_user = uri.split(":")[2]
    playlist_raw = sp.user_playlist(sp_user,uri)
    playlist_name = playlist_raw["name"]

    # clear the sonos queue
    spkr.clear_queue()

    # create and update the track list   
    playlist_tracks_raw = sp.user_playlist_tracks(sp_user,uri,limit=50,offset=0)
    playlist_tracks = {}
    
    # turn off shuffle before starting the new queue
    spkr.play_mode = 'NORMAL'

    # when not able to add a track to the queue, spotipy resets the track # to 1
    # in this case I just handled the track nr separately with n
    n = 0
    for track in playlist_tracks_raw['items']:
        n = n + 1
        #track_number = track['track']['track_number'] # disabled as causing issues with non-playable tracks
        track_number = n
        track_name = track['track']["name"]
        track_uri = track['track']["uri"]
        playlist_tracks.update({track_number: {}})
        playlist_tracks[track_number].update({"uri" : track_uri})
        playlist_tracks[track_number].update({"name" : track_name})
        logger.info(track_number)
        if track_number == int("1"):
            # play track 1 immediately
            spkr.add_uri_to_queue(uri=track_uri)
            spkr.play()
        else:
            # add all remaining tracks to queue
            spkr.add_uri_to_queue(uri=track_uri)

def handle_qrcode(qrcode):
    global last_qrcode
    store_qr = True

    # Ignore redundant codes, except for commands like "whatsong", where you might
    # want to perform it multiple times
    if qrcode == last_qrcode and not qrcode.startswith('cmd:'):
        print('IGNORING REDUNDANT QRCODE: ' + qrcode)
        return

    print('HANDLING QRCODE: ' + qrcode)

    if qrcode.startswith('cmd:'):
        handle_command(qrcode)
    elif qrcode.startswith('mode:'):
        handle_command(qrcode)
    elif qrcode.startswith('spotify:album:'):
        handle_spotify_album(qrcode)
    elif qrcode.startswith('spotify:artist:'):
        # TODO
        handle_spotify_artist(qrcode)
    elif qrcode.startswith('spotify:user:'):
        if (':playlist:') in qrcode:
            handle_spotify_playlist(qrcode)
    elif qrcode.startswith('spotify:'):
        handle_spotify_item(qrcode)
    elif qrcode.startswith('changezone:'):
        handle_command(qrcode)
    elif qrcode.startswith('pl:'):
        handle_library_item(qrcode)
    elif qrcode.startswith('trk:'):
        handle_library_item(qrcode)
    elif qrcode.startswith('alb:'):
        handle_library_item(qrcode)
    else:
        # if qr code is not recognized, don't replace valid last_qrcode
        print('QR code does not match known card patterns. Will not attempt play.')
        store_qr = False

    # Blink the onboard LED to give some visual indication that a code was handled
    # (especially useful for cases where there's no other auditory feedback, like
    # when adding songs to the queue)
    if not args.debug_file:
        blink_led()
        
    if store_qr:
        last_qrcode = qrcode


# Monitor the output of the QR code scanner.
def start_scan():
    while True:
        data = p.readline()
        qrcode = str(data)[8:]
        if qrcode:
            qrcode = qrcode.rstrip()
            handle_qrcode(qrcode)


# Read from the `debug.txt` file and handle one code at a time.
def read_debug_script():
    # Read codes from `debug.txt`
    with open(args.debug_file) as f:
        debug_codes = f.readlines()

    # Handle each code followed by a short delay
    for code in debug_codes:
        # Remove any trailing comments and newline (and ignore any empty or comment-only lines)
        code = code.split("#")[0]
        code = code.strip()
        if code:
            handle_qrcode(code)
            sleep(4)

if args.debug_file:
    # Run through a list of codes from a local file
    read_debug_script()
else:
    # Start the QR code reader
    # --nodisplay required as running pi headless, to avoid invalid argument (22) errors
    p = os.popen('/usr/bin/zbarcam --nodisplay --prescale=300x200', 'r')
    try:
        start_scan()
    except KeyboardInterrupt:
        print('Stopping scanner...')
    finally:
        GPIO.cleanup()
        p.close()

