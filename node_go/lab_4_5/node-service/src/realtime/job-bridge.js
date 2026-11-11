const { frames } = require('./ws-protocol');

// Requirement 9: the result of stream processing reaches the connected clients.
//
// This file is the entire coupling between the two modules of the lab, and it
// is deliberately the only one. StreamJobService emits events and has never
// heard of a socket; the broadcaster sends frames and has never heard of a
// pipeline. Removing this file leaves both modules working and only the
// integration gone - which is the test of whether responsibilities really are
// separated, or only filed in different folders.
//
// The frame the assignment asks for is the progress one:
//   { "type": "progress", "processed": 5242880, "total": 104857600 }
// with the derived fields the dashboard needs added next to it.
function attachJobBridge({ service, broadcaster, log = () => {} }) {
  const onStarted = ({ job }) => {
    broadcaster.broadcast(
      frames.jobEvent({
        event: 'job_started',
        jobId: job.id,
        payload: { mode: job.mode, chain: job.chain, options: job.options, datasetBytes: job.datasetBytes },
      }),
    );
  };

  // No throttling here: the service already emits at most one progress event
  // per configured interval, and the per-client rate limit is the policy's job.
  // Throttling in three places would make the real cadence unknowable.
  const onProgress = (payload) => {
    broadcaster.broadcast(frames.progress(payload));
  };

  // The processed data itself. It is the highest-volume frame in the system,
  // which is precisely why it is the one the slow-client policy is exercised
  // against in the report.
  const onChunk = (payload) => {
    broadcaster.broadcast(frames.chunk(payload));
  };

  const onScenario = ({ jobId, scenario }) => {
    broadcaster.broadcast(frames.jobEvent({ event: 'job_scenario', jobId, payload: { scenario } }));
  };

  const finish = (event) => ({ job }) => {
    log(`bridge: ${event} for job ${job.id}`);
    broadcaster.broadcast(
      frames.jobEvent({
        event,
        jobId: job.id,
        payload: {
          state: job.state,
          mode: job.mode,
          result: job.result,
          scenarios: job.scenarios,
          error: job.error,
          startedAt: job.startedAt,
          finishedAt: job.finishedAt,
        },
      }),
    );
  };

  const onDone = finish('job_done');
  const onError = finish('job_error');
  const onAborted = finish('job_aborted');

  service.on('job:started', onStarted);
  service.on('job:progress', onProgress);
  service.on('job:chunk', onChunk);
  service.on('job:scenario', onScenario);
  service.on('job:done', onDone);
  service.on('job:error', onError);
  service.on('job:aborted', onAborted);

  // Returned so a test can wire the bridge up and take it down again without
  // leaking listeners into the next test.
  return function detach() {
    service.off('job:started', onStarted);
    service.off('job:progress', onProgress);
    service.off('job:chunk', onChunk);
    service.off('job:scenario', onScenario);
    service.off('job:done', onDone);
    service.off('job:error', onError);
    service.off('job:aborted', onAborted);
  };
}

module.exports = { attachJobBridge };
