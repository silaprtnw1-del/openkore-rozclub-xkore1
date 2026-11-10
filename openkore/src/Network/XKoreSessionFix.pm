#########################################################################
#  OpenKore - XKore 1 login-sequence correction
#
#  Pure, dependency-free helpers so the logic can be unit-tested offline
#  without XSTools, sockets or Globals. See src/Network/test/xkore_chenter_rewrite.t
#
#  Background (ROZCLUB, kRO_RagexeRE_2021_11_03, XKore 1):
#  When the real client logs in twice, the second AC_ACCEPT_LOGIN (0x0AC4)
#  replaces the session IDs the login server will honour, but the client can
#  still send CH_ENTER (0x0065) carrying the FIRST login's loginID1/loginID2.
#  The character server then answers HC_REFUSE_ENTER (0x006C), which OpenKore
#  surfaces as "invalid character specified". Rewriting the CH_ENTER session
#  IDs to the newest ones the login server issued avoids the refusal.
#
#  This file is part of OpenKore and is subject to its GPL (v2 or later).
#########################################################################
package Network::XKoreSessionFix;

use strict;
use warnings;

use Exporter 'import';
our @EXPORT_OK = qw(rewrite_chenter);

use constant CH_ENTER => 0x0065;

##
# array Network::XKoreSessionFix::rewrite_chenter(scalarref msgref, Bytes sessionID, Bytes sessionID2)
#
# In place, rewrite the loginID1 (offset 6) and loginID2 (offset 10) fields of
# a CH_ENTER (0x0065) client packet referenced by $msgref to $sessionID and
# $sessionID2.
#
# CH_ENTER layout: [cmd v][accountID a4][loginID1 a4][loginID2 a4][...].
#
# Returns ($before_hex, $after_hex) of the 8 rewritten bytes when it acted, or
# an empty list when the packet is not a well-formed CH_ENTER or the session
# IDs are not usable 4-byte values. accountID and every other field are left
# untouched. Equal before/after means the IDs were already current.
sub rewrite_chenter {
	my ($msgref, $sessionID, $sessionID2) = @_;

	return () unless ref($msgref) eq 'SCALAR';
	return () unless defined $$msgref && length($$msgref) >= 14;
	return () unless unpack('v', $$msgref) == CH_ENTER;
	return () unless defined $sessionID  && length($sessionID)  == 4;
	return () unless defined $sessionID2 && length($sessionID2) == 4;

	my $before = unpack('H*', substr($$msgref, 6, 8));
	substr($$msgref, 6,  4) = $sessionID;
	substr($$msgref, 10, 4) = $sessionID2;
	my $after = unpack('H*', substr($$msgref, 6, 8));

	return ($before, $after);
}

1;
