import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js";

const STATUS_COLORS = {
  connecting: 0xff8c42,
  live: 0x00b8a9,
  warn: 0xff4d4d,
  idle: 0x6f8f7a,
  autonomy: 0x4fc3f7,
};

export class AvatarEngine {
  constructor(canvas) {
    this.canvas = canvas;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    this.camera.position.set(0, 0, 5.2);
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);

    this.timeStart = performance.now();
    this.energy = 0;
    this.listenLevel = 0;
    this.listenLevelTarget = 0;
    this.speaking = false;
    this.targetColor = new THREE.Color(STATUS_COLORS.connecting);
    this.currentColor = new THREE.Color(STATUS_COLORS.connecting);
    this.connection = "connecting";
    this.isIdle = false;
    this.autonomyActive = false;

    this._setupLights();
    this._setupMeshes();
    this._bindResize();
    this._animate = this._animate.bind(this);
    this._rafId = requestAnimationFrame(this._animate);
  }

  _setupLights() {
    const key = new THREE.DirectionalLight(0xffffff, 1.0);
    key.position.set(2, 3, 4);
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0x87fff2, 0.9);
    rim.position.set(-3, -1, 2);
    this.scene.add(rim);

    this.ambient = new THREE.AmbientLight(0x5bd8cf, 0.6);
    this.scene.add(this.ambient);
  }

  _setupMeshes() {
    this.root = new THREE.Group();
    this.scene.add(this.root);

    const orbGeo = new THREE.SphereGeometry(1.0, 64, 64);
    this.orbMat = new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.connecting,
      roughness: 0.35,
      metalness: 0.45,
      emissive: STATUS_COLORS.connecting,
      emissiveIntensity: 0.12,
    });
    this.orb = new THREE.Mesh(orbGeo, this.orbMat);
    this.root.add(this.orb);

    const shellGeo = new THREE.SphereGeometry(1.2, 48, 48);
    this.shellMat = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      transmission: 0.92,
      transparent: true,
      opacity: 0.3,
      roughness: 0.05,
      metalness: 0.0,
      clearcoat: 1,
      clearcoatRoughness: 0.02,
      ior: 1.3,
    });
    this.shell = new THREE.Mesh(shellGeo, this.shellMat);
    this.root.add(this.shell);

    const ringGeo = new THREE.TorusGeometry(1.72, 0.06, 32, 160);
    this.ringMat = new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.connecting,
      emissive: STATUS_COLORS.connecting,
      emissiveIntensity: 0.22,
      metalness: 0.85,
      roughness: 0.25,
    });
    this.ringA = new THREE.Mesh(ringGeo, this.ringMat);
    this.ringA.rotation.x = Math.PI * 0.28;
    this.root.add(this.ringA);

    this.ringB = new THREE.Mesh(ringGeo, this.ringMat.clone());
    this.ringB.rotation.y = Math.PI * 0.44;
    this.ringB.rotation.x = Math.PI * 0.74;
    this.root.add(this.ringB);

    const pulseGeo = new THREE.RingGeometry(1.8, 2.15, 96);
    this.pulseMat = new THREE.MeshBasicMaterial({
      color: STATUS_COLORS.connecting,
      transparent: true,
      opacity: 0.2,
      side: THREE.DoubleSide,
    });
    this.pulse = new THREE.Mesh(pulseGeo, this.pulseMat);
    this.pulse.rotation.x = Math.PI / 2;
    this.pulse.position.y = -1.4;
    this.root.add(this.pulse);
  }

  _bindResize() {
    const resize = () => {
      const width = Math.max(280, this.canvas.clientWidth);
      const height = Math.max(240, this.canvas.clientHeight);
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    };
    this._resizeHandler = resize;
    resize();
    window.addEventListener("resize", this._resizeHandler);
  }

  setConnection(state) {
    this.connection = state;
    if (state === "live") this.targetColor.setHex(STATUS_COLORS.live);
    if (state === "connecting") this.targetColor.setHex(STATUS_COLORS.connecting);
    if (state === "warn") this.targetColor.setHex(STATUS_COLORS.warn);
  }

  setActivity({ idle }) {
    this.isIdle = Boolean(idle);
    if (this.isIdle) {
      this.targetColor.setHex(STATUS_COLORS.idle);
    } else if (this.connection === "live") {
      this.targetColor.setHex(STATUS_COLORS.live);
    }
  }

  setAutonomyActive(active) {
    this.autonomyActive = Boolean(active);
    if (this.autonomyActive) {
      this.targetColor.setHex(STATUS_COLORS.autonomy);
    } else if (this.isIdle) {
      this.targetColor.setHex(STATUS_COLORS.idle);
    } else if (this.connection === "live") {
      this.targetColor.setHex(STATUS_COLORS.live);
    }
  }

  setListeningLevel(level) {
    this.listenLevelTarget = Math.max(0, Math.min(1, level || 0));
  }

  setSpeaking(enabled) {
    this.speaking = Boolean(enabled);
  }

  bump(amount = 0.28) {
    this.energy = Math.min(1.8, this.energy + amount);
  }

  _animate() {
    const now = performance.now();
    const t = (now - this.timeStart) / 1000;
    this.energy = Math.max(0, this.energy * 0.965);
    this.listenLevel += (this.listenLevelTarget - this.listenLevel) * 0.15;
    this.currentColor.lerp(this.targetColor, 0.06);

    this.orbMat.color.copy(this.currentColor);
    this.orbMat.emissive.copy(this.currentColor);
    this.ringMat.color.copy(this.currentColor);
    this.ringMat.emissive.copy(this.currentColor);
    this.ringB.material.color.copy(this.currentColor);
    this.ringB.material.emissive.copy(this.currentColor);
    this.pulseMat.color.copy(this.currentColor);

    const speechKick = this.speaking ? 0.1 : 0;
    const voiceKick = this.listenLevel * 0.14;
    const autonomyKick = this.autonomyActive ? 0.06 : 0;
    const basePulse = this.isIdle ? 0.96 : 1.0;
    const pulseSpeed = this.autonomyActive ? 4.2 : (this.isIdle ? 1.2 : 2.8);
    const pulseAmp = this.autonomyActive ? 0.08 : (this.isIdle ? 0.03 : 0.06);
    const wave = Math.sin(t * pulseSpeed) * pulseAmp;
    const kick = this.energy * 0.08 + speechKick + voiceKick + autonomyKick;
    const scale = basePulse + wave + kick;
    this.orb.scale.setScalar(scale);
    this.shell.scale.setScalar(1.12 + wave * 0.6 + kick * 0.7);

    const autoSpin = this.autonomyActive ? 0.008 : 0;
    this.ringA.rotation.z += 0.004 + this.energy * 0.003 + this.listenLevel * 0.01 + autoSpin;
    this.ringA.rotation.x += 0.0012 + this.listenLevel * 0.002 + autoSpin * 0.5;
    this.ringB.rotation.y -= 0.005 + this.energy * 0.004 + this.listenLevel * 0.012 + autoSpin;
    this.ringB.rotation.x -= 0.0010 + this.listenLevel * 0.002 + autoSpin * 0.5;

    const pulseScale = 1 + Math.sin(t * 2.0) * 0.06 + this.energy * 0.12 + this.listenLevel * 0.24;
    this.pulse.scale.setScalar(pulseScale);
    this.pulseMat.opacity = 0.08 + this.energy * 0.15 + this.listenLevel * 0.22;

    this.root.rotation.y = Math.sin(t * 0.28) * 0.24;
    this.root.rotation.x = Math.cos(t * 0.22) * 0.08 + this.listenLevel * 0.06;

    this.renderer.render(this.scene, this.camera);
    this._rafId = requestAnimationFrame(this._animate);
  }

  destroy() {
    if (this._rafId) {
      cancelAnimationFrame(this._rafId);
    }
    window.removeEventListener("resize", this._resizeHandler);
    this.renderer.dispose();
    this.orb.geometry.dispose();
    this.shell.geometry.dispose();
    this.ringA.geometry.dispose();
    this.pulse.geometry.dispose();
    this.orbMat.dispose();
    this.shellMat.dispose();
    this.ringMat.dispose();
    this.ringB.material.dispose();
    this.pulseMat.dispose();
  }
}
