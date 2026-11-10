#!/usr/bin/env perl
#
# Offline regression test for Network::XKoreSessionFix::rewrite_chenter.
#
# Built from the real ROZCLUB XKore 1 capture (2026-11-02 14:32 run), where a
# double login left the client's CH_ENTER (0x0065) carrying the FIRST login's
# session IDs while the login server had advanced to the SECOND login's IDs.
# The char server answered HC_REFUSE_ENTER (0x006C) -> "invalid character
# specified", and the naked 4-byte account ID that preceded it was misread by
# OpenKore as opcode "A07D".
#
# No XSTools, socket, device or live server is required.
#
#   perl src/Network/test/xkore_chenter_rewrite.t      (from the openkore root)

use strict;
use warnings;
use FindBin;
use lib "$FindBin::Bin/../../";   # openkore/src

use Test::More tests => 14;
use Network::XKoreSessionFix qw(rewrite_chenter);

# --- Captured bytes -------------------------------------------------------
# Client CH_ENTER that was refused (loginID1/2 belong to login #1).
my $chenter_bad = pack 'H*', '65007da01e002a30c1febbe0d17b000001';

# 0AC4 #2 (second AC_ACCEPT_LOGIN) payload after the 2-byte switch, unpacked
# with the stock OpenKore template 'v a4 a4 a4 ...' = (len, sessionID,
# accountID, sessionID2, ...).
my $ac4_2_payload = pack 'H*',
	'e0003f76b4f97da01e0091901cd2' . ('00' x 100);
my ($len, $sessionID, $accountID, $sessionID2) =
	unpack 'v a4 a4 a4', $ac4_2_payload;

is unpack('H*', $sessionID),  '3f76b4f9', 'sessionID  taken from 0AC4 #2';
is unpack('H*', $accountID),  '7da01e00', 'accountID  taken from 0AC4 #2';
is unpack('H*', $sessionID2), '91901cd2', 'sessionID2 taken from 0AC4 #2';

# --- 1. The real failing packet is corrected ------------------------------
{
	my $msg = $chenter_bad;
	my ($before, $after) = rewrite_chenter(\$msg, $sessionID, $sessionID2);
	ok defined($before), 'rewrite acted on the captured CH_ENTER';
	is $before, '2a30c1febbe0d17b', 'before = login #1 IDs (the refused ones)';
	is $after,  '3f76b4f991901cd2', 'after  = login #2 IDs (what the server expects)';
	isnt $before, $after, 'the packet actually changed';
	is unpack('H*', $msg),
		'65007da01e003f76b4f991901cd2000001',
		'full corrected CH_ENTER matches the expected bytes';
	is unpack('H*', substr($msg, 2, 4)), '7da01e00', 'accountID field untouched';
	is unpack('C',  substr($msg, 16, 1)), 1,          'sex byte untouched';
}

# --- 2. Idempotent when the IDs are already current -----------------------
{
	my $msg = pack 'H*', '65007da01e003f76b4f991901cd2000001';
	my ($before, $after) = rewrite_chenter(\$msg, $sessionID, $sessionID2);
	is $before, $after, 'already-current IDs produce no change (before == after)';
}

# --- 3. Guards: never touch anything that is not a clean CH_ENTER ---------
{
	my $other = pack 'H*', '64001300000041';          # a 0064-ish packet
	my @r = rewrite_chenter(\$other, $sessionID, $sessionID2);
	is scalar(@r), 0, 'non-0065 packet is left alone';

	my $short = pack 'H*', '65007da01e00';            # < 14 bytes
	@r = rewrite_chenter(\$short, $sessionID, $sessionID2);
	is scalar(@r), 0, 'truncated CH_ENTER is left alone';

	my $msg = $chenter_bad;
	@r = rewrite_chenter(\$msg, undef, $sessionID2);  # missing session ID
	is scalar(@r), 0, 'missing session ID leaves the packet alone';
}
