# qrocodile

A kid-friendly system for controlling Sonos with QR codes.

## What is it?

This is a fork of the qrocodile project originally developed by [chrispcampbell](https://github.com/chrispcampbell).
It also incorporates many chages made in a separate fork by [dernorberto](https://github.com/dernorberto).

This fork uses the [SoCo](https://github.com/SoCo/SoCo) library to control the Sonos system, rather than `node-sonos-http-api`. This makes some elements of running the controller simpler, but also requires some special consideration when preparing to use it:

* The SoCo library does not support speech through the Sonos speaker; therefore, this qrocodile does not speak in the fun way that the original does.
* Currently a [known issue](https://github.com/SoCo/SoCo/issues/557) with how the SoCo library accesses subscription-based music services prevents connecting to Spotify. Until that issue is resolved, the only way to get a qrocodile to play items via spotify is by using the `node-sonos-http-api` (i.e. by not using this fork)
* The original project actually uses a modified version of `node-sonos-http-api` that 'hashes' library tracks to make simpler QR codes for the controller camera to read. Because this version uses SoCo instead, we have to come up with our own way of [keeping QR codes simple](#keeping-qr-codes-simple).

Also, this fork was developed with my particular needs in mind. Therefore, in addition to using some code of dubious quality, it incorporates some assumptions and idiosyncracies that should be taken into account:

* Supporting mostly album-based play. Single tracks can be played, as well as playlists (both imported and Sonos playlists), but the original 'queue-building' features are not currently supported.
* Using an LED wired to one of the Raspberry Pi's GPIO ports. This is mainly used because my physical version of the qrocodile completely encases the QR code and camera, meaning that an external light is needed to illuminate the music cards. If you don't need or want the LED, you may need to remove references to the RPi.GPIO in the code.

### Keeping QR Codes Simple

The track and album metadata used to send commands to the Sonos system can vary in complexity, mostly depending on how long the artist, album, and/or track names are. This means that the corresponding QR codes can be very simple and "low-res", or very complex and therefore very hard to have read accurately by the camera used in qrocodile.

<p align="center">
    <img src="docs/images/simple_qr.png" width="40%" height="40%"> 
    <img src="docs/images/complex_qr.png" width="40%" height="40%">
</p>
<p align="center">
    Left: Simple QR code. Easy to read. Right: Complex QR code. Hard to read.
</p>

As mentioned above, the original qrocodile uses a custom version of the `node-sonos-http-api` that creates an md5 hash string from the original track information, and encodes that hash into the track's card QR code. This version allows for a similar process, and keeps track of "hashed" tracks and albums by using a dictionary lookup in a local file.

By default, single tracks are automatically hashed, because they tend to have very long URIs that would otherwise lead to too-complex QR codes. Albums may be encoded with or without the use of a hash, mainly because I figured out the "hashed" QR code approach after cuttting and gluing cards for half of my music library, and wanted to still be able to play "non-hashed" QR codes.

Unfortunately, this means that album cards require a little bit of [finicky treatment](#special-treatment-for-album-cards) to keep their QR codes simple. This includes steps for creating "hashed" and "non-hashed" cards.

## Installation and Setup

### 1. Prepare your Raspberry Pi

Originally built using a Raspberry Pi 3 Model B running Raspbian (it also works using a Raspberry Pi Zero W) and an Arducam OV5647 camera module.  Things may or may not work with other models (for example, how you control the onboard LEDs varies by model).

To set up the camera module, I had to add an entry in `/etc/modules`:

```
% sudo emacs /etc/modules
# Add bcm2835-v4l2
% sudo reboot
# After reboot, verify that camera is present
% ls -l /dev/video0
```

Next, install `zbar-tools` (used to scan for QR codes) and test it out:

```
% sudo apt-get install zbar-tools
% zbarcam --prescale=300x200
```

Optional: Make a little case to hold your RPi and camera along with a little slot to hold a card in place.

### 2. Generate some cards with `qrgen`

First, clone the `qrocodile` repo if you haven't already on your primary computer:

```
% git clone https://github.com/foldedpaper/qrocodile
% cd qrocodile
```

Next, modify the `my_defaults_example.txt` file to include the default room speaker you wish to control, and save it as `my_defaults.txt`.

#### Cards for items in your music library
To generate each card with a QR code, you will need URIs for the tracks, albums, and playlists that want to encode. `qrgen` uses a different command line argument for each of these.

To list all tracks:

```
% python3 qrgen.py --list-library-tracks
```

You can also include a search term to list matching tracks, if you are only intersted in a subset of your library:

```
% python3 qrgen.py --list-library-tracks <search term>
```

To list all albums:

```
% python3 qrgen.py --list-library-albums
```

To list all playlists:

```
% python3 qrgen.py --list-library-playlists
```

Each of these commands will write a text file to the `out` sub-directory of the project. 

Next, create a text file in the root project directory that lists the different music cards you want to create. Use one line per card, and for each card paste the URI written to the text file in the step above. 

(See `example.txt` for some possibilities.)

##### Special treatment for album cards
If you want to create cards for playing albums from your library, you will have to take an extra step for the `qrplay` script to be able to send them to the Sonos speaker.

When you create a list of library albums using the above command, the generated `all_albums.txt` file will have an entry at the top for `album_uuid_prefix`. This is a string that identifies one of the zone speakers in your Sonos system, and it is needed to construct the full album URI that is sent through SoCo to play the album. Copy this `album_uuid_prefix` to your `my_defaults.txt` file in order to enable playing albums from your local library.

As mentioned above, album cards can optionally have their metadata "hashed" to create simpler QR codes. This may not be necessary for your setup, but I find that with my RPi's camera and the low light on the bookshelf where I keep my qrocodile, the scanner tends to struggle reading QR codes for albums with long titles and/or long artist names (I start to see problems when the album title and artist title have a combined length over 50 characters or so).

Anyway, if you want to make sure that a particular album is "hashed" for easier reading, change its prefix in the text file for generating from `alb:` to `alb:hsh:`.

(Again, the included `example.txt` has an example of this.)

#### Cards for Spotify items
(N.B., as mentioned above, this SoCo-driven implementation of qrocodile currently can't play items from your Spotify account. If and when the SoCo library is updated to restore access to Spotify, I will update this fork to make sure Spotify cards can be handled by the qrocodile player. But the process for creating a Spotify item card will remain the same.)

If you want to play Spotify tracks, you will need to set up your own Spotify app token (See the `spotipy` [documentation](http://spotipy.readthedocs.io/en/latest/) for more on that.)

Spotify track URIs can be found in the Spotify app by clicking a song, then selecting "Share > Copy Spotify URI". Add this URI to the text file you will use for generating cards (like the `example.txt` file shows).

#### Finally, generate some cards:

```
% python3 qrgen.py --input example.txt --generate-images
```

This will create an `index.html` file in the `out` sub-directory of the project. This file lays out each card with its QR code and its associated artwork:
    * Track cards will attempt to find the album art of the associated album in your music library, and use that art as the card artwork. If no art is found, a generic album image is used, found in the project directory.
    * Album cards will attempt to use the associated album art from your music library. If this attempt fails or if no art is found, the generic album image is used.
    * Playlist cards use a generic playlist image.

#### Cards for commands and Sonos zones
The cards for commands and Sonos zones are generated separately.

Create command cards using `qrgen` and the text file `command_cards.txt`. Use the file `command_cards_all.txt` as a template, remove the commands you don't need and run the script to generate the cards.

```
% python3 qrgen.py --commands
% open out/commands.html
```

This will create a `commands.html` file in the `out` sub-directory of the project. Artwork for each command card is set within the `command_cards.txt` file.


Create Sonos zone cards using `qrgen`. It does not require a list file; instead, the command uses SoCo to poll your Sonos system for all available zones. 

```
% python3 qrgen.py --zones
```

This will create a `zones.html` file in the `out` sub-directory of the project. The art for these cards uses a Sonos logo in the project directory (`sonos_360.png`).

### 3. Cut and glue your cards together

### 4. Start `qrplay`

On your Raspberry Pi, clone this `qrocodile` repo:

```
% git clone https://github.com/foldedpaper/qrocodile
% cd qrocodile
```

Then, launch `qrplay`:

```
% python3 qrplay.py
```

If you want to use your own `qrocodile` as a standalone thing (not attached to a monitor, etc), you'll want to set up your RPi to launch `qrplay` when the device boots:

```
% emacs ~/.config/lxsession/LXDE-pi/autostart
# Add an entry to launch `qrplay.py`, pipe the output to a log file, etc
```

## Acknowledgments

Many thanks to chrispcampbell for creating this great project. I also benefitted from following the modifications made by dernorberto, not to say the work of the many authors of the libraries and tools used in the project.

## License

`qrocodile` is released under an MIT license, and the original code is copyright Chris Campbell. See the LICENSE file for the full license.
