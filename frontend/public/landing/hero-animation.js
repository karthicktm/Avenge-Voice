/**
 * AVENGE AI - Hero Waveform Animation
 * Canvas-based AI voice visualization
 */

class WaveformAnimation {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;

    this.ctx = this.canvas.getContext('2d');
    this.waves = [];
    this.animationId = null;
    this.time = 0;

    this.init();
  }

  init() {
    // Set canvas size
    this.resize();
    window.addEventListener('resize', () => this.resize());

    // Create multiple wave layers
    this.waves = [
      { amplitude: 30, frequency: 0.02, speed: 0.03, offset: 0, opacity: 1 },
      { amplitude: 20, frequency: 0.03, speed: 0.02, offset: Math.PI / 2, opacity: 0.6 },
      { amplitude: 15, frequency: 0.025, speed: 0.025, offset: Math.PI, opacity: 0.4 },
    ];

    // Start animation
    this.animate();
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();

    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;

    this.ctx.scale(dpr, dpr);

    this.width = rect.width;
    this.height = rect.height;
    this.centerY = this.height / 2;
  }

  drawWave(wave) {
    this.ctx.beginPath();
    this.ctx.strokeStyle = `rgba(0, 0, 0, ${wave.opacity})`;
    this.ctx.lineWidth = 2;
    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';

    // Draw smooth sine wave
    for (let x = 0; x < this.width; x++) {
      const y = this.centerY +
        Math.sin(x * wave.frequency + this.time * wave.speed + wave.offset) *
        wave.amplitude *
        (1 + Math.sin(this.time * 0.5) * 0.3); // Pulsing effect

      if (x === 0) {
        this.ctx.moveTo(x, y);
      } else {
        this.ctx.lineTo(x, y);
      }
    }

    this.ctx.stroke();
  }

  drawParticles() {
    // Add subtle particles along the main wave
    const mainWave = this.waves[0];
    const particleCount = 5;

    for (let i = 0; i < particleCount; i++) {
      const x = (this.width / particleCount) * i + (this.time * 2) % (this.width / particleCount);
      const y = this.centerY +
        Math.sin(x * mainWave.frequency + this.time * mainWave.speed) *
        mainWave.amplitude *
        (1 + Math.sin(this.time * 0.5) * 0.3);

      this.ctx.beginPath();
      this.ctx.arc(x, y, 3, 0, Math.PI * 2);
      this.ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
      this.ctx.fill();
    }
  }

  animate() {
    // Clear canvas
    this.ctx.clearRect(0, 0, this.width, this.height);

    // Draw center line (subtle)
    this.ctx.beginPath();
    this.ctx.strokeStyle = 'rgba(0, 0, 0, 0.1)';
    this.ctx.lineWidth = 1;
    this.ctx.moveTo(0, this.centerY);
    this.ctx.lineTo(this.width, this.centerY);
    this.ctx.stroke();

    // Draw all waves
    this.waves.forEach(wave => this.drawWave(wave));

    // Draw particles
    this.drawParticles();

    // Update time
    this.time += 1;

    // Continue animation
    this.animationId = requestAnimationFrame(() => this.animate());
  }

  stop() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
  }
}

// Initialize when DOM is ready
function initHeroAnimation() {
  const waveform = new WaveformAnimation('waveform');

  // Pause animation when page is not visible (performance optimization)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      waveform.stop();
    } else {
      waveform.animate();
    }
  });
}

// Check if DOM is already loaded, otherwise wait for it
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initHeroAnimation);
} else {
  // DOM is already loaded, initialize immediately
  initHeroAnimation();
}
