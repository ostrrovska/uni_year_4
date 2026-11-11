// Liveness probe. It also reports which repository implementation is wired in,
// which is what makes the memory -> file swap observable from outside without
// reading the logs.
class HealthController {
  constructor(repositoryName) {
    this.repositoryName = repositoryName;
  }

  check = (req, res) => {
    res.status(200).json({ status: 'ok', repository: this.repositoryName });
  };
}

module.exports = { HealthController };
