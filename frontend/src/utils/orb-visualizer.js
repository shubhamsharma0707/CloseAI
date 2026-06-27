import * as THREE from 'three';

let _orbState = 'idle';
let _material = null;
let _innerMat = null;
let _particlesMat = null;

const STATE_CONFIG = {
  idle: {
    color: 0x00eefc, innerColor: 0x7829ff,
    rotationSpeed: 0.2, innerRotationSpeed: -0.15,
    particleOpacity: 0.5, wireOpacity: 0.3, innerOpacity: 0.15,
    pulseFreq: 1.0, pulseAmp: 0.02,
  },
  thinking: {
    color: 0x7829ff, innerColor: 0x00eefc,
    rotationSpeed: 0.7, innerRotationSpeed: -0.5,
    particleOpacity: 0.8, wireOpacity: 0.55, innerOpacity: 0.30,
    pulseFreq: 3.0, pulseAmp: 0.06,
  },
  responding: {
    color: 0x00eefc, innerColor: 0x7829ff,
    rotationSpeed: 0.35, innerRotationSpeed: -0.25,
    particleOpacity: 0.6, wireOpacity: 0.38, innerOpacity: 0.20,
    pulseFreq: 1.8, pulseAmp: 0.03,
  },
};

/** Set the orb's visual state: 'idle' | 'thinking' | 'responding' */
export function setOrbState(state) {
  if (!STATE_CONFIG[state]) return;
  _orbState = state;
  const cfg = STATE_CONFIG[state];
  if (_material) _material.color.setHex(cfg.color);
  if (_innerMat) _innerMat.color.setHex(cfg.innerColor);
}

export function initOrb(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  const geometry = new THREE.IcosahedronGeometry(1.5, 2);
  _material = new THREE.MeshBasicMaterial({ color: 0x00eefc, wireframe: true, transparent: true, opacity: 0.3 });
  const orb = new THREE.Mesh(geometry, _material);
  scene.add(orb);

  const innerGeo = new THREE.IcosahedronGeometry(1.2, 3);
  _innerMat = new THREE.MeshBasicMaterial({ color: 0x7829ff, transparent: true, opacity: 0.15 });
  const innerOrb = new THREE.Mesh(innerGeo, _innerMat);
  scene.add(innerOrb);

  const particlesGeometry = new THREE.BufferGeometry();
  const particlesCount = 200;
  const posArray = new Float32Array(particlesCount * 3);
  for (let i = 0; i < particlesCount * 3; i++) posArray[i] = (Math.random() - 0.5) * 6;
  particlesGeometry.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
  _particlesMat = new THREE.PointsMaterial({ size: 0.05, color: 0x00eefc, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending });
  const particlesMesh = new THREE.Points(particlesGeometry, _particlesMat);
  scene.add(particlesMesh);

  camera.position.z = 4;
  const clock = new THREE.Clock();

  function animate() {
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    const cfg = STATE_CONFIG[_orbState] || STATE_CONFIG.idle;

    _material.opacity += (cfg.wireOpacity - _material.opacity) * 0.05;
    _innerMat.opacity += (cfg.innerOpacity - _innerMat.opacity) * 0.05;
    _particlesMat.opacity += (cfg.particleOpacity - _particlesMat.opacity) * 0.05;

    const pulse = 1 + Math.sin(t * cfg.pulseFreq) * cfg.pulseAmp;
    orb.scale.setScalar(pulse);

    orb.rotation.y = t * cfg.rotationSpeed;
    orb.rotation.x = t * 0.1;
    innerOrb.rotation.y = t * cfg.innerRotationSpeed;
    innerOrb.rotation.z = t * 0.1;
    particlesMesh.rotation.y = t * 0.05;

    renderer.render(scene, camera);
  }

  animate();

  window.addEventListener('resize', () => {
    if (!container) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });
}

