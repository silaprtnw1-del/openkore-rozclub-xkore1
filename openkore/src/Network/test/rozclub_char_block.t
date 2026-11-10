#!/usr/bin/env perl
#
# Offline regression test for the ROZCLUB char-block size defect.
#
# Capture: 2026-11-05 19:20 XKore 1 run. After login succeeded, the char
# server sent [naked accountID][082D][006B]. OpenKore displayed slot 0 with an
# EMPTY name and level 0/0 even though the raw payload clearly contains the
# name "potato7" and map "pay_dc01.gat".
#
# Root cause: the profile's servers.txt set `charBlockSize 155`, but this
# server's HC_ACCEPT_ENTER (006B) char block is 175 bytes (PACKETVER >=
# 20201007 struct: 64-bit hp/sp, Z24 name). received_characters() unpacks each
# block with the template that `charBlockSize` selects, so 155 reads the name
# and level fields at the wrong offsets -> empty / zero.
#
# These templates are copied verbatim from
# Network::Receive::received_characters_unpackString (keep in sync).
#
#   perl src/Network/test/rozclub_char_block.t     (from the openkore root)

use strict;
use warnings;
use Test::More tests => 9;

# 006B char block for slot 0 (175 bytes), sliced from the captured response:
# full response = [accountID 4][082D 29][006B 202]; within 006B the charInfo
# starts 27 bytes in ('v C3 x20 a*'), i.e. absolute byte 60, length 175.
my $hex = '7da01e002d081d000f00000f0f00000000000000000000000000000000000000006b00ca000f0f0f00000000000000000000000000000000000000008b060000641900000000000000000000fd010000000000000300000000000000000000000000000000000000000000000100a400000000000000eb000000000000004a000000000000004a00000000000000960006001300060001000700000000000100410b000008000000706f7461746f370000000000000000000000000000000000010b01011401000801007061795f646330312e676174000000000000000000000000000000000000000001a009050000000d020400b9089cbf00007da01e000000';
my $full = pack 'H*', $hex;

is length($full), 257, 'captured response is 257 bytes';
my $charInfo = substr($full, 60, 175);
is length($charInfo), 175, 'char block is 175 bytes (one slot)';

my %tpl = (
	155 => 'a4 V2 V V2 V6 v V2 v4 V v9 Z24 C8 v Z16 V4 C',
	175 => 'a4 V2 V V2 V6 v V2 V2 V2 V2 v2 V v9 Z24 C8 v Z16 V4 C',
);
my @keys155 = qw(charID exp exp_2 zeny exp_job exp_job_2 lv_job body_state health_state effect_state stance manner status_point hp hp_max sp sp_max walkspeed jobID hair_style weapon lv skill_point head_bottom shield head_top head_mid hair_pallete clothes_color name str agi vit int dex luk slot hair_color is_renamed last_map delete_date robe slot_addon rename_addon sex);
my @keys175 = qw(charID exp exp_2 zeny exp_job exp_job_2 lv_job body_state health_state effect_state stance manner status_point hp hp_2 hp_max hp_max_2 sp sp_2 sp_max sp_max_2 walkspeed jobID hair_style weapon lv skill_point head_bottom shield head_top head_mid hair_pallete clothes_color name str agi vit int dex luk slot hair_color is_renamed last_map delete_date robe slot_addon rename_addon sex);

sub decode {
	my ($bs) = @_;
	my @k = $bs == 155 ? @keys155 : @keys175;
	my %c;
	@c{@k} = unpack($tpl{$bs}, $charInfo);
	for (qw(name last_map)) { $c{$_} //= ''; $c{$_} =~ s/\0.*$//s; }
	return \%c;
}

# --- correct (175): the real character decodes cleanly --------------------
my $ok = decode(175);
is $ok->{name},     'potato7',      '175: name decodes to potato7';
is $ok->{lv},       7,              '175: base level is 7';
is $ok->{last_map}, 'pay_dc01.gat', '175: last_map decodes to pay_dc01.gat';
is $ok->{slot},     0,              '175: slot is 0';

# --- defect (155): reproduce the reported symptom exactly -----------------
my $bad = decode(155);
isnt $bad->{name}, 'potato7', '155 (old config): name is NOT decoded as potato7';
ok   $bad->{name} eq '' || $bad->{name} !~ /\w/, '155 (old config): name field is blank/garbage';
is   $bad->{lv},   0,         '155 (old config): base level comes out 0';
