package rozclub_market;

# ROZCLUB Market Scanner & Drop Optimizer (OpenKore plugin)
#
# Commands:
#   market scan [min_zeny]   - scan current map drops & market prices
#   market auto [min_zeny]   - same, then rewrite pickupitems.txt + items_control.txt
#   market top               - top expensive items on the market
#   market search <keyword>  - search item prices
#
# 2026-11-06 changes:
#   - The Python scanner now runs in the background. Before, backticks blocked
#     OpenKore's main loop (and, in XKore 1, the game client) until it finished.
#   - Control files are only reloaded when the scanner actually wrote them
#     (exit code 0); a failed scan (e.g. HTTP 401) no longer touches them.
#   - Only one scan runs at a time.

use strict;
# POSIX is built-in to start.exe (32-bit packaged PerlApp).
# Do NOT load external POSIX.pm from src/deps (64-bit Strawberry copy
# shadows the builtin and breaks DynaLoader). WNOHANG=1 on Windows.
use constant WNOHANG => 1;
use Time::HiRes qw(time);
use Plugins;
use Globals;
use Settings;
use Log qw(message warning error);
use Commands;
use File::Basename qw(dirname);
use File::Spec;

Plugins::register('rozclub_market', 'ROZCLUB Live Market Scanner & Drop Optimizer', \&on_unload);

my $cmd_hook = Commands::register(
    ['market', 'ROZCLUB Market Scanner (market scan | market auto [min_zeny] | market top | market search <name>)', \&cmd_market]
);
my $loop_hook = Plugins::addHook('mainLoop_post', \&poll_scanner);

# Loaded from <repo>\plugins\rozclub_market (roz.ps1 --plugins); the scanner sits in
# <repo>\tools\market_scanner (moved from C:\Users\silap\rearo on 2026-11-10).
my $SCANNER_SCRIPT = File::Spec->catfile(File::Spec->rel2abs(dirname(__FILE__)), File::Spec->updir,
                                         File::Spec->updir, 'tools', 'market_scanner', 'rozclub_market_scanner.py');
my $PYTHON = 'python';

# Running scan: { pid, out_file, apply, min, started }
my $job;
my $next_poll = 0;

sub on_unload {
    Commands::unregister($cmd_hook);
    Plugins::delHook($loop_hook);
}

sub send_thaa_market_token_request {
    return unless $net && $messageSender;
    # 0x0CF0 "THAA" type '2' asks the map server to send the market token
    # (0x0CF1) to the client's d3d9.dll; the scanner then reads it.
    eval {
        my $pkt = pack('v v a4 C', 0x0CF0, 9, 'THAA', 0x32);
        $messageSender->sendToServer($pkt);
        message "[rozclub_market] Requested a market token refresh (0x0CF0).\n", "info";
    };
}

sub start_scanner {
    my ($args_str, %opts) = @_;
    if ($job) {
        warning "[rozclub_market] A market scan is already running, please wait.\n";
        return;
    }
    my $out_file = ($Settings::logs_folder || 'logs') . '/rozclub_market_last.txt';
    unlink $out_file;
    my $cmd = qq{cmd /c ""$PYTHON" "$SCANNER_SCRIPT" $args_str > "$out_file" 2>&1"};
    my $pid = system(1, $cmd);
    if (!$pid || $pid < 0) {
        error "[rozclub_market] Could not start the scanner: $!\n";
        return;
    }
    $job = { pid => $pid, out_file => $out_file, apply => $opts{apply}, min => $opts{min}, started => time };
    message "[rozclub_market] Market scan started in the background...\n", "info";
}

sub poll_scanner {
    return unless $job;
    return if time < $next_poll;
    $next_poll = time + 0.5;

    my $res = waitpid($job->{pid}, WNOHANG);
    return if $res == 0;    # still running
    my $exit = ($res == -1) ? -1 : ($? >> 8);
    my $finished = $job;
    undef $job;

    my $output = '';
    if (open(my $fh, '<:encoding(UTF-8)', $finished->{out_file})) {
        local $/;
        $output = <$fh>;
        close $fh;
    }
    message "==================== ROZCLUB MARKET ====================\n", "list";
    message "$_\n", "list" foreach split(/\r?\n/, $output);
    message "========================================================\n", "list";

    if ($finished->{apply}) {
        if ($exit == 0) {
            eval { Commands::run("reload pickupitems.txt"); };
            eval { Commands::run("reload items_control.txt"); };
            message "[rozclub_market] Reloaded pickupitems.txt & items_control.txt (Store >= $finished->{min} Zeny, Sell < $finished->{min} Zeny)!\n", "success";
        } else {
            warning "[rozclub_market] Scan failed (exit code $exit); pickupitems.txt / items_control.txt were NOT changed.\n";
        }
    } elsif ($exit != 0) {
        warning "[rozclub_market] Scan finished with exit code $exit.\n";
    }
}

sub cmd_market {
    my (undef, $arg_line) = @_;
    $arg_line = '' unless defined $arg_line;
    $arg_line =~ s/^\s+|\s+$//g;

    my ($subcmd, $rest) = split(/\s+/, $arg_line, 2);
    $subcmd = lc($subcmd || 'scan');
    $rest = '' unless defined $rest;

    my $min = ($rest =~ /^\d+$/) ? $rest : ($config{rozclubMarket_minZeny} || 1000);

    if ($subcmd eq 'scan') {
        send_thaa_market_token_request();
        start_scanner("--min-zeny $min");
    } elsif ($subcmd eq 'auto' || $subcmd eq 'apply') {
        send_thaa_market_token_request();
        start_scanner("--min-zeny $min --apply", apply => 1, min => $min);
    } elsif ($subcmd eq 'top') {
        send_thaa_market_token_request();
        start_scanner("--top");
    } elsif ($subcmd eq 'search' && $rest ne '') {
        $rest =~ s/["&|<>^%]//g;    # keep the cmd line safe
        send_thaa_market_token_request();
        start_scanner(qq{--search "$rest"});
    } else {
        message "Usage:\n", "info";
        message "  market scan [min_zeny]   - Scan current map drops & market prices\n", "info";
        message "  market auto [min_zeny]   - Auto-update & reload pickupitems.txt + items_control.txt from live market prices\n", "info";
        message "  market top               - Show top expensive items on ROZCLUB Market\n", "info";
        message "  market search <keyword>  - Search item prices on ROZCLUB Market\n", "info";
    }
}

1;
