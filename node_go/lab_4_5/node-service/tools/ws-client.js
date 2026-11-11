const WebSocket = require('ws');

const { config } = require('../src/config');

// A WebSocket client for the demo, in three flavours:
//
//   default        a well-behaved client: identifies, subscribes, reads
//                  everything, reports what it received
//   --slow         a deliberately slow consumer (requirement 10)
//   --kill-socket  a client that dies without closing, to show the heartbeat
//                  noticing a lost connection (requirement 8)
//
// How the slow client works is worth stating plainly, because there is no
// honest way to do it from the library API: the server only slows down if TCP
// stops accepting bytes, and a Node client that merely ignores the "message"
// event still drains the socket. So the slow client pauses the underlying
// socket, which is what a client whose event loop is blocked, or whose network
// is congested, does to the server from the outside. Reaching into the socket
// is the point of the experiment, not an accident.

function parseArgs(argv) {
  const args = {
    url: `ws://localhost:${config.port}${config.ws.path}`,
    token: config.ws.token,
    name: `cli-${process.pid}`,
    topics: ['chat', 'presence', 'progress', 'chunks', 'stats'],
    slow: false,
    resumeEveryMs: 2000,
    resumeForMs: 50,
    killAfterMs: null,
    durationMs: 20000,
    say: null,
    sayEveryMs: null,
    quiet: false,
    json: false,
    invalid: 0,
    hello: true,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const [flag, inlineValue] = argv[index].split('=');
    const value = inlineValue ?? argv[index + 1];
    const consumeNext = inlineValue === undefined;
    let consumed = true;

    switch (flag) {
      case '--url': args.url = value; break;
      case '--token': args.token = value; break;
      case '--name': args.name = value; break;
      case '--topics': args.topics = value.split(','); break;
      case '--duration': args.durationMs = Number(value); break;
      case '--say': args.say = value; break;
      case '--say-every': args.sayEveryMs = Number(value); break;
      case '--resume-every': args.resumeEveryMs = Number(value); break;
      case '--resume-for': args.resumeForMs = Number(value); break;
      case '--kill-socket': args.killAfterMs = Number(value ?? 1000); break;
      case '--invalid': args.invalid = Number(value); break;
      case '--slow': args.slow = true; consumed = false; break;
      case '--no-hello': args.hello = false; consumed = false; break;
      case '--quiet': args.quiet = true; consumed = false; break;
      case '--json': args.json = true; consumed = false; break;
      case '--help':
        console.log(usage());
        process.exit(0);
        break;
      default:
        throw new Error(`unknown argument "${argv[index]}"`);
    }

    if (consumeNext && consumed) {
      index += 1;
    }
  }

  return args;
}

function usage() {
  return `Usage: node tools/ws-client.js [options]

  --name <s>          client name sent in hello, default cli-<pid>
  --token <s>         auth token, default "${config.ws.token}" (pass a wrong one to see 4401)
  --topics <a,b>      subscribe to these topics, default chat,presence,progress,chunks,stats
  --duration <ms>     how long to stay connected, default 20000
  --say <text>        send one chat message after identification
  --say-every <ms>    keep sending it on this interval
  --invalid <n>       send n malformed frames after identification
  --no-hello          never identify, to show the auth timeout closing the socket
  --slow              stop reading the socket, resuming briefly now and then
  --resume-every <ms> slow client: resume interval, default 2000
  --resume-for <ms>   slow client: how long each resume lasts, default 50
  --kill-socket <ms>  destroy the socket without closing after this delay
  --quiet             do not print every frame
  --json              print one JSON summary line at exit
`;
}

function run(args) {
  const counters = { received: 0, byType: {}, bytes: 0 };
  let clientId = null;
  let closeInfo = null;

  const ws = new WebSocket(args.url);
  const log = (...parts) => {
    if (!args.quiet) {
      console.log(...parts);
    }
  };

  const finish = () => {
    const summary = {
      name: args.name,
      clientId,
      slow: args.slow,
      received: counters.received,
      bytes: counters.bytes,
      byType: counters.byType,
      close: closeInfo,
    };

    if (args.json) {
      console.log(JSON.stringify(summary));
    } else {
      console.log('');
      console.log(`client            ${args.name} (${clientId ?? 'unidentified'})`);
      console.log(`frames received   ${counters.received} (${counters.bytes} bytes)`);
      console.log(`by type           ${JSON.stringify(counters.byType)}`);
      console.log(`closed            ${closeInfo ? `${closeInfo.code} ${closeInfo.reason}` : 'still open'}`);
    }
  };

  // Pausing the socket stops reading as well as receiving, so a client that
  // paused on "open" could never read the welcome frame and would be closed for
  // failing to identify in time. The slow consumer therefore completes the
  // handshake first and only then stops reading - which is also what a real
  // client whose rendering thread seizes up looks like.
  const becomeSlow = () => {
    const socket = ws._socket;
    socket.pause();
    log('slow client: socket paused');

    if (args.resumeEveryMs > 0 && args.resumeEveryMs < 86400000) {
      const resume = setInterval(() => {
        socket.resume();
        setTimeout(() => socket.pause(), args.resumeForMs).unref();
      }, args.resumeEveryMs);
      resume.unref();
    }
  };

  ws.on('open', () => {
    log(`open ${args.url}`);

    if (args.killAfterMs !== null) {
      // No close frame, no handshake: exactly what a killed process leaves
      // behind. The server finds out from the heartbeat.
      setTimeout(() => {
        log('destroying socket without a close handshake');
        ws._socket.destroy();
      }, args.killAfterMs).unref();
    }
  });

  ws.on('message', (raw) => {
    counters.received += 1;
    counters.bytes += raw.length;

    let frame;
    try {
      frame = JSON.parse(raw.toString('utf8'));
    } catch {
      log(`unparsable frame of ${raw.length} bytes`);
      return;
    }

    counters.byType[frame.type] = (counters.byType[frame.type] ?? 0) + 1;

    if (frame.type === 'welcome') {
      clientId = frame.clientId;
      log(`welcome, clientId=${clientId}, auth required within ${frame.authTimeoutMs} ms`);
      if (args.hello) {
        ws.send(JSON.stringify({ type: 'hello', name: args.name, token: args.token }));
      } else {
        log('--no-hello: staying silent, the server should close on its auth timeout');
      }
      return;
    }

    if (frame.type === 'ready') {
      log(`identified as ${frame.name}, peers: ${frame.peers.length}`);
      ws.send(JSON.stringify({ type: 'subscribe', topics: args.topics }));

      for (let index = 0; index < args.invalid; index += 1) {
        ws.send(index % 2 === 0 ? 'not json at all' : JSON.stringify({ type: 'nonsense' }));
      }

      if (args.say !== null) {
        ws.send(JSON.stringify({ type: 'message', text: args.say }));
        if (args.sayEveryMs !== null) {
          const timer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'message', text: args.say }));
            }
          }, args.sayEveryMs);
          timer.unref();
        }
      }

      if (args.slow) {
        // After the subscribe above, so the server has it on the progress and
        // stats topics before it stops keeping up with them.
        setTimeout(becomeSlow, 200).unref();
      }
      return;
    }

    if (frame.type === 'progress') {
      log(`progress ${frame.percent}% (${frame.processed}/${frame.total})`);
      return;
    }

    if (frame.type === 'message') {
      log(`message from ${frame.from}: ${frame.text}`);
      return;
    }

    if (frame.type === 'error') {
      log(`server error frame: ${frame.code} - ${frame.detail}`);
      return;
    }

    if (frame.type !== 'stats') {
      log(`frame ${frame.type}`);
    }
  });

  ws.on('close', (code, reason) => {
    closeInfo = { code, reason: reason?.toString() ?? '' };
    log(`close ${code} ${closeInfo.reason}`);
    finish();
    process.exit(0);
  });

  ws.on('error', (error) => {
    console.error(`socket error: ${error.message}`);
  });

  // Referenced on purpose. A paused socket deactivates its handle, so with
  // every timer unref'd the event loop would have nothing left to wait on and
  // the slow client would exit a moment after pausing - which is not the
  // experiment.
  setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      finish();
      process.exit(0);
      return;
    }

    ws.close(1000, 'client done');

    // A slow client has stopped reading, so it will never see the close frame
    // coming back and the handshake can never complete - and if the server has
    // already terminated the socket there is nobody to answer at all. Either
    // way the process has to be able to leave on its own.
    setTimeout(() => {
      if (closeInfo === null) {
        log('close handshake did not complete, terminating');
        ws.terminate();
        finish();
        process.exit(0);
      }
    }, 1500);
  }, args.durationMs);
}

if (require.main === module) {
  try {
    run(parseArgs(process.argv.slice(2)));
  } catch (error) {
    console.error(error.message);
    console.error(usage());
    process.exit(1);
  }
}

module.exports = { parseArgs, usage };
