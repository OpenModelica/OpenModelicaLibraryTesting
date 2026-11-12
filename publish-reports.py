#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Record the reports all-reports.py generated, and announce them.

Run this after the upload, never before: a report the [history] table knows
about is never generated again, so a row written before the files are up turns
any later failure in the stage into a report that is lost for good. The emails
link to those files, so they are sent from here too - after the rows, since the
other order would mail the same regressions again on every rerun.
"""

import argparse, os, sys
import simplejson as json
import resultsdb

parser = argparse.ArgumentParser(description='Record and announce published library testing reports')
parser.add_argument('--pending', default="pending-reports.json",
                    help="The reports all-reports.py generated")
parser.add_argument('--keep', default=False, action='store_true',
                    help="Do not delete the pending file, so the run can be repeated")
resultsdb.addArgument(parser)
args = parser.parse_args()

if not os.path.exists(args.pending):
  print("%s does not exist; all-reports.py generated nothing to publish" % args.pending)
  sys.exit(0)

with open(args.pending) as fin:
  pending = json.load(fin)

entries = pending.get("entries", {})
unsent = []
emails = pending.get("emails", {})

db = resultsdb.connect(args.db)
db.createHistoryTable()
for branch in sorted(entries.keys()):
  print("Recording %d reports of %s" % (len(entries[branch]), branch))
  db.insertHistory(branch, entries[branch])
db.close()

if emails:
  import smtplib
  from email.message import EmailMessage
  from email.headerregistry import Address

  missing_plain = ""
  missing_html = ""
  if pending.get("missing_branches"):
    missing_plain = "Report asks for missing branches which we ignored: %s\n" % ", ".join(pending["missing_branches"])
    missing_html = ("%s %s %s" % ("<p style=\"color:red;\">", missing_plain, "</p"))

  sent = 0
  recipients = sorted(emails.keys())
  for i, email in enumerate(recipients):
    msg = EmailMessage()
    msg['Subject'] = 'OpenModelica Library Testing Regressions'
    msg['From'] = Address("OM Hudson", "openmodelicabuilds", "ida.liu.se")
    msg['To'] = email
    msg.set_content("""\
%s
The following reports contain regressions your account was involved with:
""" % missing_plain + "\n".join(reversed(emails[email]["plain"])))
    msg.add_alternative("""\
<html lang="en">
<head></head>
<body>
%s
<p>The following reports contain regressions your account was involved with:</p>
%s
</body>
</html>
""" % (missing_html, "\n".join(reversed(emails[email]["html"]))), subtype='html')
    try:
      with smtplib.SMTP('smtp.office365.com', timeout=60) as s:
        s.starttls()
        s.ehlo()
        s.login(os.environ["IDA_EMAIL_USR"],os.environ["IDA_EMAIL_PSW"])
        try:
          s.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
          print("Skipping refused address %s: %s" % (email, e.recipients))
          continue
    except (OSError, smtplib.SMTPException) as e:
      # The rows are in the [history] table already, so a rerun would not mail
      # these regressions again: the log is the only place they are left in.
      # The mail server is not reachable for the rest of them either, and the
      # overviews this stage builds next must not be lost over it.
      unsent = recipients[i:]
      print("Could not send the emails, %s: %s" % (type(e).__name__, e))
      print("Not sent, %d of %d emails:" % (len(unsent), len(emails)))
      for address in unsent:
        print("  %s:" % address)
        for line in reversed(emails[address]["plain"]):
          print("    %s" % line)
      break
    sent += 1
  print("Sent %d of %d emails" % (sent, len(emails)))

if not args.keep:
  os.remove(args.pending)

if unsent:
  # Tells the Jenkinsfile to mark the build unstable and go on.
  sys.exit(2)
