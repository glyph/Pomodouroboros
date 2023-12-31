"""
List of explanations of the current state of the nexus.
"""

from __future__ import annotations

IDLE = """
       You're idle right now.  No need to do anything in particular.  Go ahead
       and relax!

       Your next working session will start at {nextSessionStart}.
       """

IN_SESSION = """
             You're currently in a work session, which started at
             {currentSessionStart}.

             This means that you should try to set as many intentions as
             possible before it ends at {currentSessionEnd}.
             """

ON_BREAK = """
           You're taking a break for the next {timeUntilBreakOver}.
           """

IN_POMODORO = """
              You're in the middle of a session, working on the intention
              “{intentionTitle}”.
              """

STREAK = """
         You're on a streak!  You've successfully completed {streakLength}
         pomodoros, and currenty have a score multiplier of {scoreMultiplier};
         keep it up!
         """
