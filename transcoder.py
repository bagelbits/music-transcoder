import argparse
import sys
import MySQLdb
import os
import re
from mutagen.id3 import ID3, TPE1, TPE2, TIT2, TRCK, TPOS, TALB, TDRC, TPUB, TCON, TSRC
import mutagen.id3
from subprocess import call

"""
For the transcoder.
currently, *scrubbed*{file_id}/file
transcode to *scrubbed*{file_id}/transcodes/
Trimmed go in *scrubbed*{file_id}/samples/

Script lives in  /home/music/public_html/apps/transcoder/ probably

Input:
file_id
Array of formats

Test file:
2804 .wav


Notes:
pop a warning if you try and do trim/sampling on lossy formats.
Though.... all input should be [.wav, .aif, .aiff, .flac]
ability to trim
ability to alter sample rate

Workflow:
Check file type, convert to mp3 if it isn't.
Query mm for file_id, then query for the track_id.
Then fill in ID3 tags.
Then find album_id for that track.
Query mm for the filename of the cover of that album.
Possibly resizing the album cover to 300px, ensuring it's RGB, adding instagram filters, etc.
Embed cover into track.
?????
Profit.
"""

########################
# Gather required info #
########################

def gather_track_info(track_file_id):

    global mm_cursor
    global unicorn_cursor
    global accepted_input_formats
    global args
    track_info = {}

    mm_cursor.execute("SELECT file.file_name, file_for_track.track_id, file.audio_type \
                       FROM file, file_for_track \
                       WHERE file.id = %s \
                       AND file.id = file_for_track.file_id \
                       LIMIT 1;", (track_file_id, ))
    track_file_name, track_id, track_info['orig_format'] = mm_cursor.fetchone()

    track_info['track_file_name'] = track_file_name
    track_file_path = '*scrubbed*' + str(track_file_id) \
                    + '/file/' + track_file_name


    if track_info['orig_format'] not in accepted_input_formats:
        print colorz.FAIL
        print "Track file is not in an accepted lossless format"
        print colorz.ENDC
        sys.exit(1)

    unicorn_cursor.execute("SELECT name, ISRC FROM tracks WHERE id = %s LIMIT 1;",
        (track_id,))
    track_info['track_title'], track_info['ISRC'] = unicorn_cursor.fetchone()

    unicorn_cursor.execute("SELECT clients.name\
                            FROM clients, client_tracks\
                            WHERE client_tracks.track_id = %s\
                            AND clients.id = client_tracks.client_id\
                            LIMIT 1;", (track_id, ))
    track_info['track_artist'] = unicorn_cursor.fetchone()[0]

    unicorn_cursor.execute("SELECT album_id, track_num\
                            FROM album_tracks\
                            WHERE track_id = %s\
                            LIMIT 1;", (track_id, ))
    album_id, track_info['track_number'] = unicorn_cursor.fetchone()

    unicorn_cursor.execute("SELECT name, release_date, UPC\
                            FROM albums\
                            WHERE id = %s\
                            LIMIT 1;", (album_id, ))
    track_info['album_title'], release_date, upc_code = unicorn_cursor.fetchone()
    track_info['album_year'] = str(release_date.year)

    mm_cursor.execute("SELECT file.id, file.file_name\
                       FROM file, file_for_album\
                       WHERE file_for_album.album_id = %s\
                       AND file.id = file_for_album.file_id\
                       AND file_for_album.is_cover = 1\
                       LIMIT 1;", (album_id,))
    album_file_id, album_file_name = mm_cursor.fetchone()
    track_info['album_file_path'] = '*scrubbed*' + str(album_file_id) \
                    + '/file/' + album_file_name

    genre = []
    mm_cursor.execute("SELECT genre.name\
                       FROM genre, album\
                       WHERE album.upc_code = %s\
                       AND genre.id = album.genre_primary_id\
                       LIMIT 1;", (upc_code,))
    genre.append(mm_cursor.fetchone()[0])
    mm_cursor.execute("SELECT genre.name\
                       FROM genre, album\
                       WHERE album.upc_code = %s\
                       AND genre.id = album.genre_secondary_id\
                       LIMIT 1;", (upc_code,))
    genre.append(mm_cursor.fetchone()[0])
    track_info['genre'] = " ".join(genre)

    mm_cursor.execute("SELECT disc_number\
                       FROM track\
                       WHERE ISRC = %s\
                       LIMIT 1;",(track_info['ISRC'],))
    track_info['disc_number'] = mm_cursor.fetchone()[0]

    mm_cursor.execute("SELECT label.name\
                       FROM label, artist_to_label, artist\
                       WHERE label.id = artist_to_label.label_id\
                       AND artist_to_label.artist_id = artist.id\
                       AND artist.name LIKE %s\
                       LIMIT 1;", (track_info['track_artist'],))
    track_info['label'] = mm_cursor.fetchone()[0]

    mm_cursor.execute("SELECT artist.name\
                       FROM artist, album, artist_album\
                       WHERE album.upc_code = %s\
                       AND album.id = artist_album.album_id\
                       AND artist_album.artist_id = artist.id\
                       LIMIT 1;", (upc_code,))
    track_info['album_artist'] = mm_cursor.fetchone()[0]

    for key in track_info:
        track_info[key] = str(track_info[key])

    return track_file_path, track_info


def music_transcoding(track_file_id, track_file_path, track_info, args, format='mp3'):
    #Construct the SoX command as well as make required folders just in case:
    if(not os.path.exists("*scrubbed*" + track_file_id + "/samples/")):
        os.makedirs("*scrubbed*" + track_file_id + "/samples/")
    if(not os.path.exists("*scrubbed*" + track_file_id + "/transcodes/")):
        os.makedirs("*scrubbed*" + track_file_id + "/transcodes/")

    sox_command = []
    sox_command.append("sox")
    sox_command.append(track_file_path)
    #if args.bit_rate:
    #    sox_command.extend(['-b', args.bit_rate[0]])

    if args.trim:
        out_file_path = "*scrubbed*" + track_file_id + "/samples/"\
            + track_info['track_file_name'].rsplit('.', 1)[0] + '.' + format
        sox_command.append(out_file_path)
        sox_command.extend(["trim", args.trim[0], args.trim[1]])
    else:
        out_file_path = "*scrubbed*" + track_file_id + "/transcodes/"\
            + track_info['track_file_name'].rsplit('.', 1)[0] + '.' + format
        sox_command.append(out_file_path)

    if args.sample_rate:
        sox_command.extend(["rate", args.sample_rate[0] + "k"])

    call_status = call(sox_command)

    return out_file_path

def tag_resulting_track(out_file_path, track_info):
    try:
        track_to_tag = ID3(out_file_path)
    except mutagen.id3.error:
        track_to_tag = ID3()
        track_to_tag.save(out_file_path)

    track_to_tag.add(TPE1(encoding=3, text=track_info['track_artist']))    # Artist

    track_to_tag.add(TIT2(encoding=3, text=track_info['track_title']))     # Title
    track_to_tag.add(TSRC(encoding=3, text=track_info['ISRC']))            # ISRC

    track_to_tag.add(TRCK(encoding=3, text=track_info['track_number']))    # Track Number
    track_to_tag.add(TPOS(encoding=3, text=track_info['disc_number']))     # Disc Number

    track_to_tag.add(TALB(encoding=3, text=track_info['album_title']))     # Album Title
    track_to_tag.add(TDRC(encoding=3, text=track_info['album_year']))      # Year
    track_to_tag.add(TPUB(encoding=3, text=track_info['label']))           # Label
    track_to_tag.add(TPE2(encoding=3, text=track_info['album_artist']))    # Album artist
    track_to_tag.add(TCON(encoding=3, text=track_info['genre']))           # Genre

    track_to_tag.save(out_file_path)


class colorz:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

####################
# Music Transcoder #
#   Main Method    #
####################

#############
# Constants #
#############
validArguments = False
accepted_input_formats = ['wav', 'aif', 'aiff', 'flac']

#######################
# Argument Processing #
#######################
parser = argparse.ArgumentParser("Music Transcoder")

#base options
parser.add_argument('--file_id', '-f', nargs=1, dest='file_id',
    help="file_id to transcode", metavar='file_id')
parser.add_argument('--sampe-rate', '-r', nargs=1, dest='sample_rate',
    help="Sample rate in KHz", metavar="sample_rate")
parser.add_argument('--trim', '-t', nargs=2, dest='trim',
    help="Set trim section for song in seconds", metavar=("start", "end"))
parser.add_argument('--format', '-c', nargs='*', default=['mp3'], dest='formats',
    help="Specify formats to convert to")
parser.add_argument('--bit-rate', '-b', nargs=1, dest='bit_rate',
    help="Set sample size in bits per sample")


args = parser.parse_args()

if args.file_id and args.formats:
    validArguments = True;

if not validArguments:
    print colorz.FAIL
    print "You forgot to put in your file_id. Silly goose."
    print colorz.ENDC
    sys.exit(1)


#Open require MySQL connections and usable cursors
try:
    unicorn_conn = MySQLdb.connect(host="127.0.0.1",
                                   user="sales_unicorn",
                                   passwd="*scrubbed*",
                                   db="sales_unicorn_prod")
    mm_conn = MySQLdb.connect(host="127.0.0.1",
                              user="sales_unicorn",
                              passwd="*scrubbed*",
                              db="sales_mm_prod")
except MySQLdb.Error, e:
    print colorz.FAIL
    print "Error %d: %s" % (e.args[0], e.args[1])
    print colorz.ENDC
    sys.exit (1)

unicorn_cursor = unicorn_conn.cursor()
mm_cursor = mm_conn.cursor()


#Gather info from the databases
print colorz.OKBLUE + "Gathering track data and file paths..." + colorz.ENDC
track_file_id = args.file_id[0]
track_file_path, track_info = gather_track_info(track_file_id)


print colorz.OKBLUE + "\nResults:"
print track_file_path
for key in track_info:
    print key + ": " + track_info[key]
print colorz.ENDC


#Transcode your files
print colorz.OKBLUE + "\nProcess audio file and convert to requested format....\n" + colorz.ENDC
for format in args.formats:
    print colorz.OKBLUE + "Transcoding to " + format + colorz.ENDC
    out_file_path = music_transcoding(track_file_id, track_file_path, track_info, args, format)

    #Mutagen stuff
    print colorz.OKBLUE + "Tagging the resulting transcoded file....\n" + colorz.ENDC
    tag_resulting_track(out_file_path, track_info)

print colorz.OKBLUE + "\nOKAY! DONE! <3" + colorz.ENDC
