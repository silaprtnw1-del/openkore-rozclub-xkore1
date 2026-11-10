package gui_ipc;

# ===========================================================================
# gui_ipc v2 - bridge between OpenKore and the ROZ Bot Control desktop GUI
# (gui\roz_gui.pyw). Every file lives in this instance's logs folder, so one
# GUI can watch any number of instances.
#
#   GUI -> bot : logs/cmd_input.txt   one console command per line
#   bot -> GUI : logs/status.json     rewritten once per second
#                logs/events.jsonl    one JSON object per line (died, pm, ...)
#                logs/gui_log.txt     visible console messages:
#                                     "<epoch>\t<type>\t<domain>\t<text>"
#                logs/char.json       learned skills + inventory, every 5 seconds
#
# 2026-11-09 v2: events + log export, AI state / position / nearby players
#                in status, "online" now means IN_GAME (NOT_CONNECTED is 1,
#                so the old truthiness test was always true).
# 2026-11-09 v3: party member names in status; char.json (skills + items)
#                for the GUI's skill / potion / buff-item menus.
# ===========================================================================

use strict;
use Plugins;
use Settings;
use Commands;
use Globals;
use Network;
use AI;
use Skill;
use Log qw(message error);
use Time::HiRes qw(time);

Plugins::register('gui_ipc', 'Bridge for the ROZ Bot Control GUI', \&on_unload);

my $hooks = Plugins::addHooks(
    ['mainLoop_post',                \&on_loop],
    ['self_died',                    \&on_died],
    ['disconnected',                 \&on_disconnected],
    ['in_game',                      \&on_in_game],
    ['base_level_changed',           \&on_base_level],
    ['job_level_changed',            \&on_job_level],
    ['packet_privMsg',               \&on_pm],
    ['item_gathered',                \&on_item],
    ['Network::Receive::map_changed', \&on_map_changed],
);
my $log_hook = Log::addHook(\&on_log);

my $LOG_MAX    = 2 * 1024 * 1024;   # gui_log.txt rotates to gui_log.1.txt
my $EVENTS_MAX = 512 * 1024;        # events.jsonl is truncated (GUI notices)

my $next_cmd    = 0;
my $next_status = 0;
my $next_flush  = 0;
my $next_char   = 0;
my $char_error_reported = 0;
my @log_buffer;
my @event_buffer;
my %gm_seen;          # player name -> last time we reported it
my $in_log_hook = 0;

sub on_unload {
    Plugins::delHooks($hooks);
    Log::delHook($log_hook);
    flush_files();
}

sub _dir { return $Settings::logs_folder || 'logs'; }

# --- tiny JSON encoder (no dependency on JSON::PP being on PERL5LIB) -------
sub _jstr {
    my ($s) = @_;
    $s = '' unless defined $s;
    $s =~ s/\\/\\\\/g;
    $s =~ s/"/\\"/g;
    $s =~ s/\r/\\r/g;
    $s =~ s/\n/\\n/g;
    $s =~ s/\t/\\t/g;
    $s =~ s/([\x00-\x1f])/sprintf('\\u%04x', ord($1))/ge;
    return '"' . $s . '"';
}

# Values are encoded as strings unless their key is listed in %$nums.
sub _jobj {
    my ($h, $nums) = @_;
    my @parts;
    for my $k (sort keys %$h) {
        my $v = $h->{$k};
        my $enc;
        if (ref($v) eq 'ARRAY') {
            $enc = '[' . join(',', map { _jstr($_) } @$v) . ']';
        } elsif ($nums->{$k}) {
            $enc = (defined $v && $v =~ /^-?\d+(?:\.\d+)?$/) ? $v : 0;
        } else {
            $enc = _jstr($v);
        }
        push @parts, _jstr($k) . ':' . $enc;
    }
    return '{' . join(',', @parts) . '}';
}

# --- events ----------------------------------------------------------------
sub push_event {
    my ($type, %data) = @_;
    $data{type} = $type;
    $data{ts}   = time;
    $data{char} = ($char && defined $char->{name}) ? $char->{name} : '' unless exists $data{char};
    $data{map}  = ($field ? $field->baseName : '') unless exists $data{map};
    push @event_buffer, _jobj(\%data, { ts => 1, level => 1, amount => 1 });
}

sub on_died        { push_event('died'); }
sub on_disconnected { push_event('disconnected'); }
sub on_in_game     { push_event('in_game'); }
sub on_base_level  { my (undef, $a) = @_; push_event('base_level', level => $a->{level}); }
sub on_job_level   { my (undef, $a) = @_; push_event('job_level',  level => $a->{level}); }
sub on_pm {
    my (undef, $a) = @_;
    push_event('pm', from => $a->{privMsgUser}, msg => $a->{privMsg});
}
sub on_item {
    my (undef, $a) = @_;
    push_event('item', item => $a->{item}, amount => $a->{amount});
}
sub on_map_changed {
    push_event('map_changed');
}

# --- console messages -> gui_log.txt ---------------------------------------
sub on_log {
    my ($type, $domain, $level, $verbosity, $msg) = @_;
    return if $in_log_hook;
    return if $type eq 'debug';
    return if defined $level && defined $verbosity && $level > $verbosity;
    $in_log_hook = 1;
    my $text = defined $msg ? $msg : '';
    $text =~ s/[\r\n]+$//;
    $text =~ s/[\r\n\t]+/ /g;
    if ($text ne '') {
        push @log_buffer, sprintf("%.1f\t%s\t%s\t%s\n", time, $type, (defined $domain ? $domain : ''), $text);
        shift @log_buffer while @log_buffer > 2000;
    }
    $in_log_hook = 0;
}

sub _append {
    my ($file, $max, $rotate_to, @lines) = @_;
    return unless @lines;
    if (-f $file && -s $file > $max) {
        if ($rotate_to) { unlink $rotate_to; rename($file, $rotate_to); }
        else            { unlink $file; }
    }
    if (open(my $fh, '>>:utf8', $file)) {
        print $fh @lines;
        close $fh;
    }
}

sub flush_files {
    my $dir = _dir();
    if (@log_buffer) {
        my @l = @log_buffer; @log_buffer = ();
        _append("$dir/gui_log.txt", $LOG_MAX, "$dir/gui_log.1.txt", @l);
    }
    if (@event_buffer) {
        my @e = map { "$_\n" } @event_buffer; @event_buffer = ();
        _append("$dir/events.jsonl", $EVENTS_MAX, undef, @e);
    }
}

# --- main loop ---------------------------------------------------------------
sub on_loop {
    my $now = time;
    if ($now >= $next_cmd)    { $next_cmd = $now + 0.25; check_input(); }
    if ($now >= $next_status) { $next_status = $now + 1; write_status(); }
    if ($now >= $next_flush)  { $next_flush = $now + 0.5; flush_files(); }
    if ($now >= $next_char) {
        $next_char = $now + 5;
        # Optional data for menus: a failure must never disturb the bot. Report it once.
        if (!eval { write_char(); 1 }) {
            my $err = $@ || 'unknown error';
            error "[gui_ipc] char.json not written: $err" unless $char_error_reported++;
        }
    }
}

# --- learned skills + inventory -> char.json (for the GUI menus) -----------
sub write_char {
    return unless $char && $net && $net->getState() == Network::IN_GAME;
    my @skills;
    for my $handle (sort keys %{ $char->{skills} || {} }) {
        my $lv = $char->{skills}{$handle}{lv};
        next unless $lv;
        my ($name, $target) = ($handle, -1);
        eval {
            my $sk = Skill->new(handle => $handle);
            $name = $sk->getName() || $handle;
            my $t = $sk->getTargetType();
            $target = $t if defined $t;
        };
        push @skills, _jobj({ handle => $handle, name => $name, lv => $lv, target => $target },
                            { lv => 1, target => 1 });
    }
    # Whole skill tree, level 0 included (the "skills" list above holds learned ones only):
    # the GUI's auto skill raise lets the user pick skills not learned yet. up = can be raised.
    my @tree;
    for my $handle (sort keys %{ $char->{skills} || {} }) {
        my $sk = $char->{skills}{$handle};
        my $name = $handle;
        eval { $name = Skill->new(handle => $handle)->getName() || $handle; };
        push @tree, _jobj({ handle => $handle, name => $name, lv => ($sk->{lv} || 0), up => ($sk->{up} ? 1 : 0) },
                          { lv => 1, up => 1 });
    }
    # Base stats, bonuses and unspent points (Network/Receive.pm stat_info / stats_info).
    my %st = (lv => $char->{lv} || 0, points_free => $char->{points_free} || 0,
              points_skill => $char->{points_skill} || 0);
    for my $s (qw(str agi vit int dex luk)) {
        $st{$s} = $char->{$s} || 0;
        $st{"${s}_bonus"} = $char->{"${s}_bonus"} || 0;
    }
    my $stats = _jobj(\%st, { map { $_ => 1 } keys %st });
    my @items;
    my $inv = $char->inventory;
    if ($inv) {
        for my $it (@{ $inv->getItems() }) {
            push @items, _jobj({ id => $it->{nameID}, name => $it->{name}, amount => $it->{amount},
                                 type => $it->{type}, equipped => ($it->{equipped} ? 1 : 0) },
                               { id => 1, amount => 1, type => 1, equipped => 1 });
        }
    }
    my $json = sprintf('{"ts":%.1f,"char":%s,"skills":[%s],"tree":[%s],"stats":%s,"items":[%s]}',
                       time, _jstr($char->{name}), join(',', @skills), join(',', @tree), $stats, join(',', @items));
    my $file = _dir() . '/char.json';
    if (open(my $fh, '>:utf8', "$file.tmp")) {
        print $fh $json;
        close $fh;
        rename("$file.tmp", $file);
    }
}

sub check_input {
    my $dir  = _dir();
    my $file = "$dir/cmd_input.txt";
    return unless -f $file;
    my $work = "$dir/cmd_input.processing";
    # Rename first: if the GUI is still writing, the rename fails and we
    # simply try again on the next tick instead of losing a line.
    return unless rename($file, $work);
    my @lines;
    if (open(my $fh, '<:encoding(UTF-8)', $work)) {
        @lines = <$fh>;
        close $fh;
    }
    unlink $work;
    for my $line (@lines) {
        $line =~ s/^\x{FEFF}//;
        $line =~ s/^\s+|\s+$//g;
        next if $line eq '';
        message "[GUI] $line\n", "connection";
        eval { Commands::run($line); };
        error "[GUI] command '$line' failed: $@\n" if $@;
    }
}

sub _n { my ($v) = @_; return (defined $v && $v ne '') ? $v + 0 : 0; }

sub write_status {
    my $state = $net ? $net->getState() : 0;
    my %s = (
        ts         => sprintf('%.1f', time),
        pid        => $$,
        state      => $state,
        online     => ($state == Network::IN_GAME ? 1 : 0),
        ai         => (AI::state() == AI::AUTO ? 'auto' : AI::state() == AI::MANUAL ? 'manual' : 'off'),
        action     => (AI::action() || ''),
        lockMap    => ($config{lockMap} || ''),
        master     => ($config{master} || ''),
        char => '', map => '', job => '', party => '',
        hp => 0, hp_max => 0, sp => 0, sp_max => 0,
        exp => 0, exp_max => 0, exp_job => 0, exp_job_max => 0,
        level => 0, level_job => 0, zeny => 0, weight => 0, weight_max => 0,
        dead => 0, sit => 0, x => 0, y => 0,
        players => 0, monsters => 0, gms => [], party_members => [],
        # characters of the account as "slot:name" (known from the character screen on)
        chars => [ map { "$_:$chars[$_]{name}" } grep { $chars[$_] && defined $chars[$_]{name} } 0 .. $#chars ],
    );

    if ($char) {
        $s{char}        = $char->{name} if defined $char->{name};
        $s{map}         = $field->baseName if $field;
        $s{job}         = $jobs_lut{$char->{jobID}} if defined $char->{jobID} && $jobs_lut{$char->{jobID}};
        $s{hp}          = _n($char->{hp});
        $s{hp_max}      = _n($char->{hp_max});
        $s{sp}          = _n($char->{sp});
        $s{sp_max}      = _n($char->{sp_max});
        $s{exp}         = _n($char->{exp});
        $s{exp_max}     = _n($char->{exp_max});
        $s{exp_job}     = _n($char->{exp_job});
        $s{exp_job_max} = _n($char->{exp_job_max});
        $s{level}       = _n($char->{lv});
        $s{level_job}   = _n($char->{lv_job});
        $s{zeny}        = _n($char->{zeny});
        $s{weight}      = _n($char->{weight});
        $s{weight_max}  = _n($char->{weight_max});
        $s{dead}        = $char->{dead} ? 1 : 0;
        $s{sit}         = $char->{sitting} ? 1 : 0;
        $s{party}       = $char->{party}{name}
            if ref($char->{party}) eq 'HASH' && defined $char->{party}{name};
        if (ref($char->{party}) eq 'HASH' && ref($char->{party}{users}) eq 'HASH') {
            # Members are Actor::Party objects (blessed hashes), so ref() is not 'HASH'.
            $s{party_members} = [ sort grep { defined && $_ ne '' && $_ ne ($char->{name} || '') }
                                   map { $_->{name} } grep { UNIVERSAL::isa($_, 'HASH') } values %{ $char->{party}{users} } ];
        }
        my $pos = eval { $field ? $char->position() : undef } || $char->{pos_to};
        if (ref($pos) eq 'HASH') { $s{x} = _n($pos->{x}); $s{y} = _n($pos->{y}); }
    }

    if ($s{online}) {
        my @players  = $playersList  ? @{$playersList->getItems()}  : ();
        my @monsters = $monstersList ? @{$monstersList->getItems()} : ();
        $s{players}  = scalar @players;
        $s{monsters} = scalar @monsters;
        my $now = time;
        for my $p (@players) {
            my $name = $p->{name};
            next unless defined $name && $name =~ /(?:^|[^A-Za-z])(?:GM|Admin|Staff)(?:[^A-Za-z]|$)/i;
            push @{$s{gms}}, $name;
            if (!$gm_seen{$name} || $now - $gm_seen{$name} > 600) {
                $gm_seen{$name} = $now;
                push_event('gm_near', who => $name);
            }
        }
    }

    my $json = _jobj(\%s, { map { $_ => 1 } qw(
        ts pid state online hp hp_max sp sp_max exp exp_max exp_job exp_job_max
        level level_job zeny weight weight_max dead sit x y players monsters) });

    my $file = _dir() . '/status.json';
    my $tmp  = "$file.tmp";
    if (open(my $fh, '>:utf8', $tmp)) {
        print $fh $json;
        close $fh;
        rename($tmp, $file);   # Perl's Win32 rename replaces the old file
    }
}

1;
