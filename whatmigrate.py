#!/usr/bin/python2

import os, re, ConfigParser, argparse, sys, locale
import exporter, siteconnection, clientconnection, migrator
from BeautifulSoup import BeautifulSoup
try: import readline # not supported on all platforms
except ImportError: pass

class Main:
    def __init__(self): 
        # take default locale
        locale.setlocale(locale.LC_ALL, '')

        # parse arguments
        parser = argparse.ArgumentParser(description='A What.CD tool to help you with migrating your old data to the new torrent.')
        group = parser.add_argument_group('manual migration')
        group.add_argument('datadir',help='directory of old torrent data',nargs='?')
        group.add_argument('torrent',help='new .torrent file, torrent id or torrent url (optional)',nargs='?')
        parser.add_argument('--version',action='version',version='whatmigrate 0.2')
        self.args = parser.parse_args()

        # parse configuration file (or create if it doesn't exist)
        self.cfg = ConfigParser.ConfigParser()
        defaultoptions = (
            ("general",(("outputdir",""),("torrentdir",""))),
            ("rtorrent",(("xmlrpc_proxy",""),("progressive","1"))),
            ("what.cd",(("username",""),("password",""),("use_ssl","1")))
        )
        if not self.cfg.read(os.path.expanduser("~/.whatmigrate")):
            print "Creating configuration file. Edit ~/.whatmigrate to configure."
            for section in defaultoptions:
                self.cfg.add_section(section[0])
                for item in section[1]:
                    self.cfg.set(section[0],item[0],item[1])
            self.cfg.write(open(os.path.expanduser("~/.whatmigrate"),"wb"))
        else:
            # check if all settings are in the config file
            written = False
            for section in defaultoptions:
                if not self.cfg.has_section(section[0]): 
                    self.cfg.add_section(section[0])
                    written = True
                for item in section[1]:
                    if not self.cfg.has_option(section[0],item[0]):
                        self.cfg.set(section[0],item[0],item[1])
                        written = True
            if written:    
                self.cfg.write(open(os.path.expanduser("~/.whatmigrate"),"wb"))

        # need an output dir to run script
        if not self.cfg.get("general","outputdir"):
            sys.exit("Please configure the output directory in ~/.whatmigrate.")

        # initialize torrentclient
        self.torrentclient = None
        if self.cfg.get("rtorrent","xmlrpc_proxy"):
            self.torrentclient = clientconnection.Rtorrent(self.cfg.get("rtorrent","xmlrpc_proxy"))

        # initialize site connection if needed
        self.siteconnection = None
        if self.cfg.get("what.cd","username") and self.cfg.get("what.cd","password"):
            self.siteconnection = siteconnection.Connection(self.cfg.get("what.cd","username"),self.cfg.get("what.cd","password"),int(self.cfg.get("what.cd","use_ssl")))
        
        # initialize migrator
        self.migrator = migrator.Migrator(self.cfg.get("general","outputdir"),self.torrentclient,self.cfg.get("general","torrentdir"))
        
        # go!
        self.start()

    def start(self):
        # manual migration
        if self.args.datadir:
            self.manualMigration()
        # guided rtorrent migration
        elif self.cfg.get("rtorrent","xmlrpc_proxy"):
            self.guidedMigration()
        # no torrent client configured and no datadir specified
        else: 
            sys.exit("No torrent client configured. Edit ~/.whatmigrate or specify a data directory (see -h)")

    # manual migration
    def manualMigration(self):
        # check if directory is valid
        if not os.path.isdir(self.args.datadir):
            sys.exit("The specified datadir is invalid.")
        # read specified torrent file or query replacement
        if self.args.torrent:
            torrentinfo = self.grabFromInput(self.args.torrent)
        else:
            searchterm = unicode(BeautifulSoup(os.path.dirname(os.path.join(self.args.datadir,''))).contents[0])
            torrentinfo = self.queryReplacement(searchterm)
        if torrentinfo:
            self.migrator.execute(torrentinfo,unicode(BeautifulSoup(self.args.datadir).contents[0]))

    # guided migration using torrent client to read 
    def guidedMigration(self):
        # get a list of unregistered torrents
        if int(self.cfg.get("rtorrent","progressive")):
            print "Scanning for unregistered torrents..."
            count = 0
            for torrentid, torrentfile, torrentfolder in self.torrentclient.unregistered_torrents_iter():
                self.guidedExecute(torrentid,torrentfile,torrentfolder)
                count += 1
            if count == 0:
                print "No unregistered torrents found"
                exit()
        else:
            print "Scanning for unregistered torrents... (can take a few minutes)"
            torrents = self.torrentclient.get_unregistered_torrents()
            if not len(torrents):
                print "No unregistered torrents found"
                exit()
            print "%d unregistered torrents found\n" % (len(torrents),)
            for torrentid, torrentfile, torrentfolder in torrents:
                self.guidedExecute(torrentid,torrentfile,torrentfolder)
    def guidedExecute(self,torrentid,torrentfile,torrentfolder):
            basename = os.path.splitext(os.path.basename(torrentfile))[0]
            basename = unicode(BeautifulSoup(basename,convertEntities=BeautifulSoup.HTML_ENTITIES).contents[0])
            print basename
            parts = basename.split(" - ")
            searchstring = parts[0] + " - " + parts[1]
            torrentinfo = self.queryReplacement(searchstring)
            if torrentinfo:
                self.migrator.execute(torrentinfo,torrentfolder,torrentid)
            print ""

    # read torrent file
    def readTorrentFile(self,path):
        if not os.path.isfile(path):
            sys.exit("Cannot read %s" % (path,))
        try:
            f = open(path,'r')
            data = f.read()
        except IOError:
            sys.exit("File %s could not be opened." % (path,))
        return data;

    # parse user input of torrent id, link or path
    def grabFromInput(self,userinput):
        # torrent id
        torrentdata = None
        if userinput.isdigit():
            if not self.siteconnection:
                sys.exit("You need to put your username and password in .whatmigrate to download a torrent.")
            torrentfile, torrentdata = self.siteconnection.getTorrentFile(int(userinput))
        # torrent permalink
        elif userinput.find('http://') != -1 or userinput.find('https://') != -1:
            if not self.siteconnection:
                sys.exit("You need to put your username and password in .whatmigrate to download a torrent.")
            regex = re.compile(r"torrents\.php\?.*id=(\d+)")
            result = regex.search(userinput)
            if result:
                torrentfile, torrentdata = self.siteconnection.getTorrentFile(int(result.group(1)))
            else:
                sys.exit("URL not recognized.")
        # path
        elif userinput:
            torrentdata = self.readTorrentFile(userinput)
            torrentfile = os.path.basename(userinput)
        # if there's data, parse and return 
        if torrentdata:
            return (torrentfile, torrentdata)
        else:
            return False

    # query user for a replacement torrent
    def queryReplacement(self,searchFor):
        # Ask for input
        print " Specify a torrent file (id, permalink or local file), leave blank to do a site search or type 's' to skip this torrent"
        if readline:
            readline.set_completer_delims(' \t\n;')
            readline.parse_and_bind("tab: complete") # enable auto-completion
        userinput = raw_input(" ")
        if readline:
            readline.parse_and_bind("tab:"); # disable auto-completion again
        if userinput.strip() == 's':
            return False
        if userinput:
            return self.grabFromInput(userinput)

        # search site for this album 
        if not self.siteconnection:
            sys.exit("You need to put your username and password in .whatmigrate to do a site search.")
        if readline: readline.set_startup_hook(lambda: readline.insert_text(searchFor.encode('utf-8')))
        userinput = raw_input(" Search What.CD for: ")
        if readline: readline.set_startup_hook()
        results = self.siteconnection.searchTorrents(userinput)
        count = 1
        flattened = []
        if results:
            # display the torrents
            for group,groupval in results.iteritems():
                print "  "+group
                for edition,editionval in groupval.iteritems():
                    print "    "+edition
                    for torrent in editionval:
                        print "      %u. %s (%s)" % (count,torrent['format'],torrent['size'])
                        flattened.append(torrent)
                        count += 1
            # ask for user entry
            userinput = raw_input(" Try migration to one of these results? (resultnumber/n) ")
            if userinput and userinput.isdigit() and int(userinput) in range(1,len(flattened)+1):
                # download the torrent file
                torrent_filename, torrentdata = self.siteconnection.getTorrentFile(flattened[int(userinput)-1]['id'])
                return (torrent_filename, torrentdata)
            else:
                return self.queryReplacement(searchFor)
        else:
            print "  No torrents found."
            # try again
            return self.queryReplacement(searchFor)


# Init
if __name__ == "__main__":
    main = Main() 
