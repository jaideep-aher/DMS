/**
 * vision.js — MediaPipe Face Mesh + metric computation
 * EAR (Eye Aspect Ratio), MAR (Mouth Aspect Ratio), Head Pose via PnP
 */

// ---------------------------------------------------------------------------
// MediaPipe Face Mesh landmark indices
// ---------------------------------------------------------------------------

// Left eye  (from viewer's perspective = person's right eye)
const LEFT_EYE  = [362, 385, 387, 263, 373, 380];
// Right eye (from viewer's perspective = person's left eye)
const RIGHT_EYE = [33,  160, 158, 133, 153, 144];

// Inner lip landmarks for MAR
// top: 13, bottom: 14, left: 78, right: 308 (simple 4-point)
// Extended: top-mid 13, top-left 312, top-right 82, bottom-mid 14, bot-left 317, bot-right 87
const MOUTH_TOP    = [13, 312, 82];
const MOUTH_BOTTOM = [14, 317, 87];
const MOUTH_LEFT   = 78;
const MOUTH_RIGHT  = 308;

// Head pose 2D->3D correspondences (indices into 468-landmark mesh)
// Nose tip, Chin, Left eye corner, Right eye corner, Left mouth, Right mouth
const POSE_LANDMARKS_IDX = [1, 152, 263, 33, 287, 57];

// Approximate 3D model points (generic face model, mm scale)
const MODEL_POINTS_3D = [
  [0.0,    0.0,    0.0  ],   // Nose tip
  [0.0,   -63.6,  -12.5],   // Chin
  [-43.3,  32.7,  -26.0],   // Left eye outer corner
  [ 43.3,  32.7,  -26.0],   // Right eye outer corner
  [-28.9, -28.9,  -24.1],   // Left mouth corner
  [ 28.9, -28.9,  -24.1],   // Right mouth corner
];

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function dist2D(a, b) {
  const dx = a.x - b.x, dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function eyeAspectRatio(landmarks, indices) {
  // EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)
  const [p1, p2, p3, p4, p5, p6] = indices.map(i => landmarks[i]);
  const v1 = dist2D(p2, p6);
  const v2 = dist2D(p3, p5);
  const h  = dist2D(p1, p4);
  return h > 0 ? (v1 + v2) / (2.0 * h) : 0;
}

function mouthAspectRatio(landmarks) {
  // MAR = vertical opening / horizontal width
  // Use 4-point: top=13, bottom=14, left=78, right=308
  const top    = landmarks[13];
  const bottom = landmarks[14];
  const left   = landmarks[78];
  const right  = landmarks[308];

  const vertical   = dist2D(top, bottom);
  const horizontal = dist2D(left, right);
  return horizontal > 0 ? vertical / horizontal : 0;
}

// ---------------------------------------------------------------------------
// Head pose estimation (simplified algebraic, no OpenCV needed in JS)
// Uses a direct linear approach based on 2D-3D correspondences:
// Decomposes rotation into pitch/yaw/roll via perspective projection.
// ---------------------------------------------------------------------------

function estimateHeadPose(landmarks, canvasWidth, canvasHeight) {
  const focalLength = canvasWidth;  // approximate
  const cx = canvasWidth  / 2;
  const cy = canvasHeight / 2;

  // 2D image points
  const pts2D = POSE_LANDMARKS_IDX.map(i => [
    landmarks[i].x * canvasWidth,
    landmarks[i].y * canvasHeight,
  ]);

  // Solve PnP iteratively (Levenberg-Marquardt lite)
  // We use a simplified approach: Weak perspective + rotation via SVD-free method
  // Based on: Guo et al. "A Simple and Robust Method for Head Pose Estimation"

  const n = pts2D.length;
  const pts3D = MODEL_POINTS_3D;

  // Normalize 2D points
  const norm2D = pts2D.map(([x, y]) => [(x - cx) / focalLength, (y - cy) / focalLength]);

  // Build linear system for rotation/translation (DLT approach simplified)
  // Use centroid alignment method
  const c2D = norm2D.reduce((a, p) => [a[0]+p[0]/n, a[1]+p[1]/n], [0,0]);
  const c3D = pts3D.reduce((a, p) => [a[0]+p[0]/n, a[1]+p[1]/n, a[2]+p[2]/n], [0,0,0]);

  const q2D = norm2D.map(p => [p[0]-c2D[0], p[1]-c2D[1]]);
  const q3D = pts3D.map(p => [p[0]-c3D[0], p[1]-c3D[1], p[2]-c3D[2]]);

  // Build 2x3 matrix M = sum(q2D_i^T * q3D_i) via least-squares
  let M = [[0,0,0],[0,0,0]];
  for (let i = 0; i < n; i++) {
    M[0][0] += q2D[i][0] * q3D[i][0];
    M[0][1] += q2D[i][0] * q3D[i][1];
    M[0][2] += q2D[i][0] * q3D[i][2];
    M[1][0] += q2D[i][1] * q3D[i][0];
    M[1][1] += q2D[i][1] * q3D[i][1];
    M[1][2] += q2D[i][1] * q3D[i][2];
  }

  // Extract rotation rows r1, r2 from M (normalize them)
  const r1raw = M[0];
  const r2raw = M[1];
  const norm1 = Math.sqrt(r1raw[0]**2 + r1raw[1]**2 + r1raw[2]**2) || 1;
  const norm2 = Math.sqrt(r2raw[0]**2 + r2raw[1]**2 + r2raw[2]**2) || 1;
  const r1 = r1raw.map(v => v / norm1);
  const r2 = r2raw.map(v => v / norm2);

  // r3 = r1 × r2
  const r3 = [
    r1[1]*r2[2] - r1[2]*r2[1],
    r1[2]*r2[0] - r1[0]*r2[2],
    r1[0]*r2[1] - r1[1]*r2[0],
  ];

  // Rotation matrix R = [r1; r2; r3]
  const R = [r1, r2, r3];

  // Extract Euler angles from rotation matrix
  // pitch = atan2(-R[2][0], sqrt(R[2][1]^2 + R[2][2]^2))  (x-axis rotation)
  // yaw   = atan2(R[1][0], R[0][0])                        (y-axis rotation)
  // roll  = atan2(R[2][1], R[2][2])                        (z-axis rotation)
  const sy = Math.sqrt(R[0][0]**2 + R[1][0]**2);
  const singular = sy < 1e-6;

  let pitch, yaw, roll;
  if (!singular) {
    pitch = Math.atan2(-R[2][0], sy);
    yaw   = Math.atan2(R[1][0], R[0][0]);
    roll  = Math.atan2(R[2][1], R[2][2]);
  } else {
    pitch = Math.atan2(-R[2][0], sy);
    yaw   = 0;
    roll  = Math.atan2(-R[1][2], R[1][1]);
  }

  const toDeg = v => v * (180 / Math.PI);
  return {
    pitch: toDeg(pitch),
    yaw:   toDeg(yaw),
    roll:  toDeg(roll),
  };
}

// ---------------------------------------------------------------------------
// Canvas drawing
// ---------------------------------------------------------------------------

function drawMeshAndMetrics(ctx, landmarks, metrics, canvasWidth, canvasHeight) {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight);

  // Draw face mesh dots
  ctx.fillStyle = 'rgba(0, 255, 100, 0.5)';
  for (const lm of landmarks) {
    ctx.beginPath();
    ctx.arc(lm.x * canvasWidth, lm.y * canvasHeight, 1.5, 0, 2 * Math.PI);
    ctx.fill();
  }

  // Highlight eye landmarks
  const highlightEye = (indices, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    indices.forEach((idx, i) => {
      const lm = landmarks[idx];
      const x = lm.x * canvasWidth, y = lm.y * canvasHeight;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
  };
  highlightEye(LEFT_EYE,  '#00cfff');
  highlightEye(RIGHT_EYE, '#00cfff');

  // Highlight mouth
  ctx.strokeStyle = '#ff9900';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  [[78,82,13,312,308,317,14,87,78]].forEach(path => {
    path.forEach((idx, i) => {
      const lm = landmarks[idx];
      const x = lm.x * canvasWidth, y = lm.y * canvasHeight;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
  });
  ctx.stroke();

  // HUD overlay
  const ear   = metrics.ear.toFixed(3);
  const mar   = metrics.mar.toFixed(3);
  const pitch = metrics.pitch.toFixed(1);
  const yaw   = metrics.yaw.toFixed(1);
  const roll  = metrics.roll.toFixed(1);

  const drowsy     = metrics.ear < 0.25;
  const yawning    = metrics.mar > 0.6;
  const distracted = Math.abs(metrics.yaw) > 20 || Math.abs(metrics.pitch) > 20;

  // Semi-transparent panel
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(8, 8, 210, 130);

  ctx.font = '13px monospace';
  const lines = [
    { label: 'EAR', value: ear,   alert: drowsy },
    { label: 'MAR', value: mar,   alert: yawning },
    { label: 'Pitch', value: `${pitch}°`, alert: Math.abs(metrics.pitch) > 20 },
    { label: 'Yaw',   value: `${yaw}°`,  alert: Math.abs(metrics.yaw) > 20 },
    { label: 'Roll',  value: `${roll}°`, alert: Math.abs(metrics.roll) > 30 },
  ];
  lines.forEach(({ label, value, alert }, i) => {
    ctx.fillStyle = alert ? '#ff4444' : '#ccffcc';
    ctx.fillText(`${label.padEnd(6)}: ${value}`, 16, 28 + i * 22);
  });

  // Big alert banners
  if (drowsy) {
    ctx.fillStyle = 'rgba(255,0,0,0.35)';
    ctx.fillRect(0, canvasHeight - 50, canvasWidth, 50);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 20px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('DROWSINESS DETECTED', canvasWidth / 2, canvasHeight - 18);
    ctx.textAlign = 'left';
  } else if (distracted) {
    ctx.fillStyle = 'rgba(255,140,0,0.35)';
    ctx.fillRect(0, canvasHeight - 50, canvasWidth, 50);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 20px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('DISTRACTION DETECTED', canvasWidth / 2, canvasHeight - 18);
    ctx.textAlign = 'left';
  }
}

// ---------------------------------------------------------------------------
// Main pipeline — called by index.html after MediaPipe is ready
// ---------------------------------------------------------------------------

function startVisionPipeline(videoEl, canvasEl, onMetrics) {
  const ctx = canvasEl.getContext('2d');

  const faceMesh = new FaceMesh({
    locateFile: file =>
      `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${file}`,
  });

  faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: true,
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });

  faceMesh.onResults(results => {
    const W = canvasEl.width;
    const H = canvasEl.height;

    // Mirror the video frame onto canvas
    ctx.save();
    ctx.scale(-1, 1);
    ctx.drawImage(results.image, -W, 0, W, H);
    ctx.restore();

    if (!results.multiFaceLandmarks || results.multiFaceLandmarks.length === 0) {
      // No face — draw "no face" notice
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.fillRect(0, 0, W, 36);
      ctx.fillStyle = '#ffff00';
      ctx.font = '14px monospace';
      ctx.fillText('No face detected', 10, 22);
      return;
    }

    const landmarks = results.multiFaceLandmarks[0];

    // Mirror landmark X coords to match mirrored video
    const mirroredLandmarks = landmarks.map(lm => ({
      x: 1 - lm.x,
      y: lm.y,
      z: lm.z,
    }));

    const earLeft  = eyeAspectRatio(mirroredLandmarks, LEFT_EYE);
    const earRight = eyeAspectRatio(mirroredLandmarks, RIGHT_EYE);
    const ear      = (earLeft + earRight) / 2;
    const mar      = mouthAspectRatio(mirroredLandmarks);
    const pose     = estimateHeadPose(mirroredLandmarks, W, H);

    const metrics = {
      timestamp: Date.now(),
      ear,
      ear_left:  earLeft,
      ear_right: earRight,
      mar,
      pitch: pose.pitch,
      yaw:   pose.yaw,
      roll:  pose.roll,
    };

    drawMeshAndMetrics(ctx, mirroredLandmarks, metrics, W, H);
    onMetrics(metrics);
  });

  const camera = new Camera(videoEl, {
    onFrame: async () => {
      await faceMesh.send({ image: videoEl });
    },
    width: 640,
    height: 480,
  });

  camera.start();
}
