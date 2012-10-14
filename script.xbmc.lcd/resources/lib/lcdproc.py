'''
    XBMC LCDproc addon
    Copyright (C) 2012 Team XBMC

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
'''

import platform
import xbmc
import xbmcgui
import sys
import os
import re
import telnetlib
import time

from socket import *

__scriptname__ = sys.modules[ "__main__" ].__scriptname__
__settings__ = sys.modules[ "__main__" ].__settings__
__cwd__ = sys.modules[ "__main__" ].__cwd__
__icon__ = sys.modules[ "__main__" ].__icon__

from settings import *
from lcdbase import *

def log(loglevel, msg):
  xbmc.log("### [%s] - %s" % (__scriptname__,msg,),level=loglevel ) 
  
SCROLL_SPEED_IN_MSEC = 250
MAX_ROWS = 20
MAX_BIGDIGITS = 20
INIT_RETRY_INTERVAL = 2
INIT_RETRY_INTERVAL_MAX = 60000

class LCDProc(LcdBase):
  def __init__(self):
    self.m_iActualpos   = 0
    self.m_iBackLight   = 32
    self.m_iLCDContrast = 50
    self.m_bStop        = True
    self.m_sockfd       = -1
    self.m_lastInitAttempt = 0
    self.m_initRetryInterval = INIT_RETRY_INTERVAL
    self.m_used = True
    self.tn = telnetlib.Telnet()
    self.m_timeLastSockAction = time.time()
    self.m_timeSocketIdleTimeout = 2
    self.m_strLineText = [None]*MAX_ROWS
    self.m_strLineType = [None]*MAX_ROWS
    self.m_strLineIcon = [None]*MAX_ROWS
    self.m_strDigits = [None]*MAX_BIGDIGITS
    self.m_iProgressBarWidth = 0
    self.m_iProgressBarLine = -1
    self.m_strIconName = "BLOCK_FILLED"
    self.m_iBigDigits = int(8) # 12:45:78 / colons count as digit
    self.m_strSetLineCmds = ""
    LcdBase.__init__(self)

  def SendCommand(self, strCmd, bCheckRet):
    countcmds = string.count(strCmd, '\n')
    sendcmd = strCmd
    ret = True

    # Single command without lf
    if countcmds < 1:
      #countcmds = 1
      sendcmd += "\n"

    try:
      # Send to server
      self.tn.write(sendcmd)
    except:
      # Something bad happened, abort
      log(xbmc.LOGERROR, "SendCommand: Telnet exception - send")
      return False

    # Update last socketaction timestamp
    self.m_timeLastSockAction = time.time()
    
    # Repeat for number of found commands
    for i in range(1, (countcmds + 1)):
      # Read in (multiple) responses
      while True:
        try:
          # Read server reply
          reply = self.tn.read_until("\n",3)            
        except:
          # (Re)read failed, abort
          log(xbmc.LOGERROR, "SendCommand: Telnet exception - reread")
          return False

        # Skip these messages
        if reply[:6] == 'listen':
          continue
        elif reply[:6] == 'ignore':
          continue
        elif reply[:3] == 'key':
          continue
        elif reply[:9] == 'menuevent':
          continue

        # Response seems interesting, so stop here      
        break
      
      if not bCheckRet:
        continue # no return checking desired, so be fine

      if strCmd == 'noop' and reply == 'noop complete\n':
        continue # noop has special reply

      if reply == 'success\n':
        continue
      
      ret = False

    # Leave information something undesired happened
    if ret is False:
      log(xbmc.LOGWARNING, "Reply to '" + strCmd +"' was '" + reply)

    return ret

  def SetupScreen(self):
    # Add screen first
    if not self.SendCommand("screen_add xbmc", True):
      return False

    # Set screen priority
    if not self.SendCommand("screen_set xbmc -priority info", True):
      return False

    # Turn off heartbeat if desired
    if not settings_getHeartBeat():
      if not self.SendCommand("screen_set xbmc -heartbeat off", True):
        return False

    # Setup widgets
    for i in range(1,int(self.m_iRows)+1):
      # Text widgets
      if not self.SendCommand("widget_add xbmc lineScroller" + str(i) + " scroller", True):
        return False

      # Progress bars
      if not self.SendCommand("widget_add xbmc lineProgress" + str(i) + " hbar", True):
        return False

      # Icons
      if not self.SendCommand("widget_add xbmc lineIcon" + str(i) + " icon", True):
        return False

      # Default icon
      if not self.SendCommand("widget_set xbmc lineIcon" + str(i) + " 0 0 BLOCK_FILLED", True):
        return False

    for i in range(1,int(self.m_iBigDigits + 1)):
      # Big Digit
      if not self.SendCommand("widget_add xbmc lineBigDigit" + str(i) + " num", True):
        return False

      # Set Digit
      if not self.SendCommand("widget_set xbmc lineBigDigit" + str(i) + " 0 0", True):
        return False

    return True

  def Initialize(self):
    connected = False
    if not self.m_used:
      return False#nothing to do

    #don't try to initialize too often
    now = time.time()
    if (now - self.m_lastInitAttempt) < self.m_initRetryInterval:
      return False
    self.m_lastInitAttempt = now

    if self.Connect():
      # reset the retry interval after a successful connect
      self.m_initRetryInterval = INIT_RETRY_INTERVAL
      self.m_bStop = False
      connected = True
    else:
      self.CloseSocket()

    if not connected:
      # give up after 60 seconds
      if self.m_initRetryInterval > INIT_RETRY_INTERVAL_MAX:
        self.m_used = False
        log(xbmc.LOGERROR,"Connect failed. Giving up.")
      else:
        self.m_initRetryInterval = self.m_initRetryInterval * 2
        log(xbmc.LOGERROR,"Connect failed. Retry in %d seconds." % self.m_initRetryInterval)
    else:
      LcdBase.Initialize(self)

    return connected

  def Connect(self):
    self.CloseSocket()

    try:
      ip = settings_getHostIp()
      port = settings_getHostPort()
      log(xbmc.LOGDEBUG,"Open " + str(ip) + ":" + str(port))
      
      self.tn.open(ip, port)
      # Start a new session
      self.tn.write("hello\n")
      # time.sleep(1)
      # Receive LCDproc data to determine row and column information
      reply = self.tn.read_until("\n",3)
      log(xbmc.LOGDEBUG,"Reply: " + reply)
      
      lcdinfo = re.match("^connect .+ protocol ([0-9\.]+) lcd wid (\d+) hgt (\d+) cellwid (\d+) cellhgt (\d+)$", reply)

      if lcdinfo is None:
        return False

      # protocol version must currently be 0.3
      if float(lcdinfo.group(1)) != 0.3:
        log(xbmc.LOGERROR, "Only LCDproc protocol 0.3 supported (got " + lcdinfo.group(1) +")")
        return False

      self.m_iColumns = int(lcdinfo.group(2))
      self.m_iRows  = int(lcdinfo.group(3))
      self.m_iCellWidth = int(lcdinfo.group(4))
      self.m_iCellHeight = int(lcdinfo.group(5))
      log(xbmc.LOGDEBUG, "LCDproc data: Columns %s - Rows %s - CellWidth %s - CellHeight %s" % (str(self.m_iColumns), str(self.m_iRows), str(self.m_iCellWidth), str(self.m_iCellHeight)))

      # Retrieve driver name for additional functionality
      self.tn.write("info\n")
      reply = self.tn.read_until("\n",3)
      log(xbmc.LOGDEBUG,"info Reply: " + reply)

      if self.m_iColumns < 16:
        self.m_iBigDigits = 5
      elif self.m_iColumns < 20:
        self.m_iBigDigits = 7

    except:
      log(xbmc.LOGERROR,"Connect: Telnet exception.")
      return False

    if not self.SetupScreen():
      log(xbmc.LOGERROR, "Screen setup failed!")
      return False      

    return True

  def CloseSocket(self):
    self.tn.close()

  def IsConnected(self):
    if self.tn.get_socket() == None:
      return False

    # Ping only every SocketIdleTimeout seconds
    if (self.m_timeLastSockAction + self.m_timeSocketIdleTimeout) > time.time():
      return True

    if not self.SendCommand("noop", True):
      log(xbmc.LOGERROR, "noop failed in IsConnected(), aborting!")
      return False

    return True

  def SetBackLight(self, iLight):
    if self.tn.get_socket() == None:
      return
    log(xbmc.LOGDEBUG, "Switch Backlight to: " + str(iLight))

    # Build command
    if iLight == 0:
      self.m_bStop = True
      cmd = "screen_set xbmc -backlight off\n"
    elif iLight > 0:
      self.m_bStop = False
      cmd = "screen_set xbmc -backlight on\n"

    # Send to server
    if not self.SendCommand(cmd, True):
      log(xbmc.LOGERROR, "SetBackLight(): Cannot change backlight state")
      self.CloseSocket()

  def SetContrast(self, iContrast):
    #TODO: Not sure if you can control contrast from client
    return

  def Stop(self):
    self.CloseSocket()
    self.m_bStop = True

  def Suspend(self):
    if self.m_bStop or self.tn.get_socket() == None:
      return

    # Build command to suspend screen
    cmd = "screen_set xbmc -priority hidden\n"

    # Send to server
    if not self.SendCommand(cmd, True):
      log(xbmc.LOGERROR, "Suspend(): Cannot suspend")
      self.CloseSocket()

  def Resume(self):
    if self.m_bStop or self.tn.get_socket() == None:
      return

    # Build command to resume screen
    cmd = "screen_set xbmc -priority info\n"

    # Send to server
    if not self.SendCommand(cmd, True):
      log(xbmc.LOGERROR, "Resume(): Cannot resume")
      self.CloseSocket()

  def GetColumns(self):
    return int(self.m_iColumns)

  def SetProgressBar(self, percent, pxWidth):
    self.m_iProgressBarWidth = int(float(percent) * pxWidth)
    return self.m_iProgressBarWidth

  def SetPlayingStateIcon(self):
    bPlaying = xbmc.getCondVisibility("Player.Playing")
    bPaused = xbmc.getCondVisibility("Player.Paused")
    bForwarding = xbmc.getCondVisibility("Player.Forwarding")
    bRewinding = xbmc.getCondVisibility("Player.Rewinding")

    self.m_strIconName = "STOP"

    if bForwarding:
      self.m_strIconName = "FF"
    elif bRewinding:
      self.m_strIconName = "FR"
    elif bPaused:
      self.m_strIconName = "PAUSE"
    elif bPlaying:
      self.m_strIconName = "PLAY"

  def GetRows(self):
    return int(self.m_iRows)

  def ClearLine(self, iLine):
    self.m_strSetLineCmds += "widget_set xbmc lineIcon%i 0 0 BLOCK_FILLED\n" % (iLine)
    self.m_strSetLineCmds += "widget_set xbmc lineProgress%i 0 0 0\n" % (iLine)
    self.m_strSetLineCmds += "widget_set xbmc lineScroller%i 1 %i %i %i m 1 \"\"\n" % (iLine, iLine, self.m_iColumns, iLine)
    
  def SetLine(self, iLine, strLine, dictDescriptor, bForce):
    if self.m_bStop or self.tn.get_socket() == None:
      return

    if iLine < 0 or iLine >= int(self.m_iRows):
      return

    ln = iLine + 1
    bExtraForce = False

    if self.m_strLineType[iLine] != dictDescriptor['type']:
      self.ClearLine(int(iLine + 1))
      self.m_strLineType[iLine] = dictDescriptor['type']
      bExtraForce = True

      if dictDescriptor['type'] == LCD_LINETYPE.LCD_LINETYPE_PROGRESS and dictDescriptor['text'] != "":
        self.m_strSetLineCmds += "widget_set xbmc lineScroller%i 1 %i %i %i m 1 \"%s\"\n" % (ln, ln, self.m_iColumns, ln, dictDescriptor['text'])

    if dictDescriptor['type'] == LCD_LINETYPE.LCD_LINETYPE_BIGSCREEN:
      strLineLong = xbmc.getInfoLabel("Player.Time")
    else:
      strLineLong = strLine

    strLineLong.strip()

    # make string fit the display if it's smaller than the width
    if len(strLineLong) < int(self.m_iColumns):
      numSpaces = int(self.m_iColumns) - len(strLineLong)
      strLineLong.ljust(numSpaces) #pad with spaces
    elif len(strLineLong) > int(self.m_iColumns): #else if the string doesn't fit the display, lcdproc will scroll it, so add separator
      strLineLong += self.m_strScrollSeparator

    # check if update is required
    if strLineLong != self.m_strLineText[iLine] or bForce:
      # progressbar line
      if dictDescriptor['type'] == LCD_LINETYPE.LCD_LINETYPE_PROGRESS:
        self.m_strSetLineCmds += "widget_set xbmc lineProgress%i %i %i %i\n" % (ln, dictDescriptor['startx'], ln, self.m_iProgressBarWidth)
      # everything else (text, icontext)
      else:
        self.m_strSetLineCmds += "widget_set xbmc lineScroller%i %i %i %i %i m %i \"%s\"\n" % (ln, dictDescriptor['startx'], ln, self.m_iColumns, ln, settings_getScrollDelay(), re.escape(strLineLong))

      # cache contents
      self.m_strLineText[iLine] = strLineLong

    if dictDescriptor['type'] == LCD_LINETYPE.LCD_LINETYPE_ICONTEXT:
      if self.m_strLineIcon[iLine] != self.m_strIconName or bExtraForce:
        self.m_strLineIcon[iLine] = self.m_strIconName
        
        self.m_strSetLineCmds += "widget_set xbmc lineIcon%i %i 1 %s\n" % (ln, ln, self.m_strIconName)

  def ClearDisplay(self):
    log(xbmc.LOGDEBUG, "Clearing display contents")

    # clear line buffer first
    self.FlushLines()

    # set all widgets to empty stuff and/or offscreen
    for i in range(1,int(self.m_iRows)+1):
      self.ClearLine(i)

    # send to display
    self.FlushLines()

  def FlushLines(self):
      #log(xbmc.LOGDEBUG, "Flushing Command List:" + self.m_strSetLineCmds)

      if len(self.m_strSetLineCmds) > 0:
        # Send complete command package
        self.SendCommand(self.m_strSetLineCmds, False)

        self.m_strSetLineCmds = ""
