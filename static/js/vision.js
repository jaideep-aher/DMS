/**
 * MediaPipe Face Mesh (client-side) + EAR / MAR / head pose (PnP via OpenCV.js when available).
 */
(function () {
  const MP_VER = "0.4.1633559619";
  const MP_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@${MP_VER}`;
  const UTIL_BASE = "https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils@0.3.1675466862";
  const DRAW_BASE = "https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils@0.3.1675466124";

  // 6-point EAR (Soukupová & Čech), indices for MediaPipe Face Mesh
  const LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144];
  const RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380];

  // Inner lip region — 6 landmarks, EAR-style ordering around inner mouth
  const MOUTH_INNER_INDICES = [78, 81, 13, 311, 308, 402];

  // PnP: 2D landmark indices matching MODEL_POINTS order
  const PNP_2D_IDX = [1, 152, 33, 263, 61, 291];

  /** Refined mesh: iris centers (first index of each iris pentagon). */
  const RIGHT_IRIS_CENTER = 468;
  const LEFT_IRIS_CENTER = 473;
  const LEFT_EYE_OUTER = 33;
  const LEFT_EYE_INNER = 133;
  const LEFT_EYE_TOP = 159;
  const LEFT_EYE_BOTTOM = 145;
  const RIGHT_EYE_OUTER = 263;
  const RIGHT_EYE_INNER = 362;
  const RIGHT_EYE_TOP = 386;
  const RIGHT_EYE_BOTTOM = 374;

  // 3D face model (mm), nose tip at origin — common OpenCV head-pose tutorial model
  const MODEL_POINTS = [
    [0.0, 0.0, 0.0],
    [0.0, -330.0, -65.0],
    [-225.0, 170.0, -135.0],
    [225.0, 170.0, -135.0],
    [-150.0, -150.0, -125.0],
    [150.0, -150.0, -125.0],
  ];

  const videoEl = document.getElementById("video");
  const canvasEl = document.getElementById("canvas");
  const statusEl = document.getElementById("status");

  let demoT0 = null;

  function isDemoMode() {
    const el = document.getElementById("demo-toggle");
    return !!(el && el.checked);
  }

  const demoToggle = document.getElementById("demo-toggle");
  if (demoToggle) {
    demoToggle.addEventListener("change", () => {
      if (demoToggle.checked) {
        demoT0 = performance.now();
      } else {
        demoT0 = null;
      }
    });
  }

  /**
   * Override metrics for demos: gradually reduce EAR and inject periodic high MAR (yawn).
   */
  function applyDemoMetrics(earL, earR, mar) {
    if (!isDemoMode() || demoT0 === null) {
      return { earL, earR, mar };
    }
    const elapsed = (performance.now() - demoT0) / 1000;
    const drift = Math.min(0.9, elapsed * 0.03);
    let outL = Math.max(0.03, earL * (1 - drift));
    let outR = Math.max(0.03, earR * (1 - drift));
    let outM = mar;
    const cycle = elapsed % 12;
    if (cycle > 3.5 && cycle < 5.2) {
      outM = Math.max(outM, 0.5 + 0.06 * Math.sin(elapsed * 2.8));
    }
    if (cycle > 8.5 && cycle < 9.8) {
      outM = Math.max(outM, 0.46);
    }
    return { earL: outL, earR: outR, mar: outM };
  }

  /**
   * Map iris position within each eye to ~[-1,1] (horizontal: outer→inner, vertical: top→bottom).
   */
  /** Horizontal iris offset vs eye midline; ~[-1,1] when iris stays inside eye opening. */
  function irisNormH(lm, irisIdx, cornerA, cornerB, w, h) {
    const ix = lm[irisIdx].x * w;
    const ax = lm[cornerA].x * w;
    const bx = lm[cornerB].x * w;
    const mid = (ax + bx) / 2;
    const half = Math.abs(bx - ax) / 2;
    if (half < 1e-4) return 0;
    return Math.max(-1.2, Math.min(1.2, (ix - mid) / half));
  }

  function irisNormV(lm, irisIdx, topIdx, botIdx, w, h) {
    const iy = lm[irisIdx].y * h;
    const ty = lm[topIdx].y * h;
    const by = lm[botIdx].y * h;
    const span = Math.abs(by - ty);
    if (span < 1e-4) return 0;
    const t = (iy - ty) / span;
    return (t - 0.5) * 2;
  }

  function combineHeadHint(yawDeg, pitchDeg) {
    const hy = Math.max(-1, Math.min(1, yawDeg / 32));
    const hp = Math.max(-1, Math.min(1, pitchDeg / 22));
    return { hy, hp };
  }

  /**
   * Coarse attention region for DMS (selfie camera, in-cabin).
   */
  function classifyGazeRegion(gn, gp, yaw, pitch, hasIris) {
    const { hy, hp } = combineHeadHint(yaw, pitch);
    const cx = hasIris ? gn * 0.62 + hy * 0.38 : hy;
    const cy = hasIris ? gp * 0.62 + hp * 0.38 : hp;

    if (cy > 0.4) return "down";
    if (cy < -0.36) return "up";
    if (cx < -0.38) return "left";
    if (cx > 0.38) return "right";
    if (Math.abs(cx) > 0.26 || Math.abs(cy) > 0.28) return "away";
    return "forward";
  }

  function computeGaze(lm, w, h, yaw, pitch) {
    const n = lm.length;
    const hasIris = n > RIGHT_IRIS_CENTER && n > LEFT_IRIS_CENTER;
    let gn = 0;
    let gp = 0;
    if (hasIris) {
      const hL = irisNormH(lm, LEFT_IRIS_CENTER, LEFT_EYE_OUTER, LEFT_EYE_INNER, w, h);
      const hR = irisNormH(lm, RIGHT_IRIS_CENTER, RIGHT_EYE_OUTER, RIGHT_EYE_INNER, w, h);
      const vL = irisNormV(lm, LEFT_IRIS_CENTER, LEFT_EYE_TOP, LEFT_EYE_BOTTOM, w, h);
      const vR = irisNormV(lm, RIGHT_IRIS_CENTER, RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM, w, h);
      gn = (hL + hR) / 2;
      gp = (vL + vR) / 2;
    }
    const region = classifyGazeRegion(gn, gp, yaw, pitch, hasIris);
    return { gaze_yaw_norm: gn, gaze_pitch_norm: gp, gaze_region: region };
  }

  function applyDemoGaze(gaze) {
    if (!isDemoMode() || demoT0 === null) return gaze;
    const elapsed = (performance.now() - demoT0) / 1000;
    const phase = elapsed % 28;
    if (phase > 11 && phase < 15) {
      return { gaze_yaw_norm: 0.05, gaze_pitch_norm: 0.75, gaze_region: "down" };
    }
    if (phase > 19 && phase < 22) {
      return { gaze_yaw_norm: -0.68, gaze_pitch_norm: 0.02, gaze_region: "left" };
    }
    return gaze;
  }

  let ctx = null;
  let faceMesh = null;
  let camera = null;
  let cvReady = false;
  let rvec = null;
  let tvec = null;
  let camMat = null;
  let distCoeffs = null;
  let objPoints = null;

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.crossOrigin = "anonymous";
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Failed to load " + src));
      document.head.appendChild(s);
    });
  }

  async function loadOpenCv() {
    try {
      await loadScript(
        "https://unpkg.com/@techstark/opencv-js@4.9.0-release.3/dist/opencv.js"
      );
      await new Promise((resolve, reject) => {
        const t = window.setTimeout(() => reject(new Error("OpenCV timeout")), 15000);
        if (typeof cv === "undefined") {
          window.clearTimeout(t);
          reject(new Error("OpenCV global missing"));
          return;
        }
        cv["onRuntimeInitialized"] = () => {
          window.clearTimeout(t);
          cvReady = true;
          initCvMats();
          resolve();
        };
      });
      setStatus("Camera + face mesh + PnP ready");
    } catch (e) {
      console.warn("OpenCV.js unavailable, using geometric head pose:", e);
      cvReady = false;
      setStatus("Camera + face mesh ready (geometric head pose)");
    }
  }

  function initCvMats() {
    if (!cvReady) return;
    rvec = new cv.Mat(3, 1, cv.CV_64FC1);
    tvec = new cv.Mat(3, 1, cv.CV_64FC1);
    distCoeffs = cv.Mat.zeros(4, 1, cv.CV_64FC1);
    const flat = [];
    for (let i = 0; i < MODEL_POINTS.length; i++) {
      flat.push(MODEL_POINTS[i][0], MODEL_POINTS[i][1], MODEL_POINTS[i][2]);
    }
    objPoints = cv.matFromArray(6, 3, cv.CV_64FC1, flat);
  }

  function lmPx(landmarks, idx, w, h) {
    const p = landmarks[idx];
    return { x: p.x * w, y: p.y * h };
  }

  function dist2(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  /** 6-point aspect ratio (EAR / MAR style). Points p1–p6: horizontal extremes + two vertical pairs. */
  function aspectRatio6(landmarks, indices, w, h) {
    const pts = indices.map((i) => lmPx(landmarks, i, w, h));
    const p1 = pts[0];
    const p2 = pts[1];
    const p3 = pts[2];
    const p4 = pts[3];
    const p5 = pts[4];
    const p6 = pts[5];
    const v1 = dist2(p2, p6);
    const v2 = dist2(p3, p5);
    const h0 = dist2(p1, p4);
    if (h0 < 1e-6) return 0;
    return (v1 + v2) / (2 * h0);
  }

  function headPoseGeometric(landmarks, w, h) {
    const le = lmPx(landmarks, 33, w, h);
    const re = lmPx(landmarks, 263, w, h);
    const nose = lmPx(landmarks, 1, w, h);
    const chin = lmPx(landmarks, 152, w, h);
    const mid = { x: (le.x + re.x) / 2, y: (le.y + re.y) / 2 };
    const roll = (Math.atan2(re.y - le.y, re.x - le.x) * 180) / Math.PI;
    const faceW = Math.max(dist2(le, re), 1e-6);
    const yaw = (-Math.atan2(nose.x - mid.x, faceW * 0.35) * 180) / Math.PI;
    const eyeY = mid.y;
    const pitch =
      (-Math.atan2(nose.y - eyeY, Math.abs(chin.y - nose.y) + 1e-6) * 180) / Math.PI;
    return { yaw, pitch, roll };
  }

  function headPosePnP(landmarks, w, h) {
    if (!cvReady || !objPoints) return headPoseGeometric(landmarks, w, h);

    const fx = w;
    const fy = w;
    const cx = w / 2;
    const cy = h / 2;
    if (!camMat) {
      camMat = cv.matFromArray(3, 3, cv.CV_64FC1, [fx, 0, cx, 0, fy, cy, 0, 0, 1]);
    } else {
      camMat.data64F[0] = fx;
      camMat.data64F[4] = fy;
      camMat.data64F[2] = cx;
      camMat.data64F[5] = cy;
    }

    const imgFlat = [];
    for (let i = 0; i < PNP_2D_IDX.length; i++) {
      const p = lmPx(landmarks, PNP_2D_IDX[i], w, h);
      imgFlat.push(p.x, p.y);
    }
    const imgPoints = cv.matFromArray(6, 2, cv.CV_64FC1, imgFlat);

    try {
      cv.solvePnP(
        objPoints,
        imgPoints,
        camMat,
        distCoeffs,
        rvec,
        tvec,
        false,
        cv.SOLVEPNP_ITERATIVE
      );

      const rotM = new cv.Mat();
      cv.Rodrigues(rvec, rotM);
      const R = rotM.data64F;
      const sy = Math.sqrt(R[0] * R[0] + R[3] * R[3]);
      let pitch;
      let yaw;
      let roll;
      if (sy > 1e-6) {
        pitch = Math.atan2(R[7], R[8]);
        yaw = Math.atan2(-R[6], sy);
        roll = Math.atan2(R[3], R[0]);
      } else {
        pitch = Math.atan2(-R[5], R[4]);
        yaw = Math.atan2(-R[6], sy);
        roll = 0;
      }
      rotM.delete();
      imgPoints.delete();
      const rad = 180 / Math.PI;
      return { yaw: yaw * rad, pitch: pitch * rad, roll: roll * rad };
    } catch (e) {
      imgPoints.delete();
      return headPoseGeometric(landmarks, w, h);
    }
  }

  function dispatchMetric(sample) {
    window.dispatchEvent(new CustomEvent("dms-metric", { detail: sample }));
  }

  function onResults(results) {
    const w = canvasEl.width;
    const h = canvasEl.height;
    ctx.save();
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(results.image, 0, 0, w, h);

    if (results.multiFaceLandmarks && results.multiFaceLandmarks.length > 0) {
      const lm = results.multiFaceLandmarks[0];

      if (typeof drawConnectors === "function" && typeof FACEMESH_TESSELATION !== "undefined") {
        drawConnectors(ctx, lm, FACEMESH_TESSELATION, {
          color: "rgba(92, 179, 154, 0.22)",
          lineWidth: 1,
        });
        drawConnectors(ctx, lm, FACEMESH_RIGHT_EYE, { color: "rgba(92, 179, 154, 0.75)", lineWidth: 1 });
        drawConnectors(ctx, lm, FACEMESH_LEFT_EYE, { color: "rgba(129, 168, 190, 0.7)", lineWidth: 1 });
        drawConnectors(ctx, lm, FACEMESH_LIPS, { color: "rgba(201, 160, 122, 0.65)", lineWidth: 1 });
      }

      const earL = aspectRatio6(lm, LEFT_EYE_INDICES, w, h);
      const earR = aspectRatio6(lm, RIGHT_EYE_INDICES, w, h);
      const mar = aspectRatio6(lm, MOUTH_INNER_INDICES, w, h);
      const pose = headPosePnP(lm, w, h);

      const dm = applyDemoMetrics(earL, earR, mar);
      const outL = dm.earL;
      const outR = dm.earR;
      const outM = dm.mar;
      const gazeRaw = computeGaze(lm, w, h, pose.yaw, pose.pitch);
      const gaze = applyDemoGaze(gazeRaw);

      const ts =
        typeof performance !== "undefined" && performance.now
          ? performance.now()
          : Date.now();

      dispatchMetric({
        ear_left: outL,
        ear_right: outR,
        mar: outM,
        yaw: pose.yaw,
        pitch: pose.pitch,
        roll: pose.roll,
        gaze_yaw_norm: gaze.gaze_yaw_norm,
        gaze_pitch_norm: gaze.gaze_pitch_norm,
        gaze_region: gaze.gaze_region,
        timestamp: ts,
      });

      const lines = [
        `EAR L: ${outL.toFixed(3)}  R: ${outR.toFixed(3)}${isDemoMode() ? " (demo)" : ""}`,
        `MAR: ${outM.toFixed(3)}`,
        `Yaw: ${pose.yaw.toFixed(1)}°  Pitch: ${pose.pitch.toFixed(1)}°  Roll: ${pose.roll.toFixed(1)}°`,
        `Attention: ${gaze.gaze_region}  (gaze y ${gaze.gaze_yaw_norm.toFixed(2)} p ${gaze.gaze_pitch_norm.toFixed(2)})`,
      ];
      ctx.fillStyle = "rgba(12, 14, 17, 0.82)";
      ctx.fillRect(8, 8, 520, 92);
      ctx.fillStyle = "#e8eaef";
      ctx.font = "500 13px 'DM Sans', system-ui, sans-serif";
      lines.forEach((line, i) => ctx.fillText(line, 16, 28 + i * 20));
    }

    ctx.restore();
  }

  async function start() {
    ctx = canvasEl.getContext("2d");
    setStatus("Loading OpenCV…");
    await loadOpenCv();

    setStatus("Loading MediaPipe…");
    await loadScript(`${UTIL_BASE}/camera_utils.js`);
    await loadScript(`${DRAW_BASE}/drawing_utils.js`);
    await loadScript(`${MP_BASE}/face_mesh.js`);

    faceMesh = new FaceMesh({
      locateFile: (file) => `${MP_BASE}/${file}`,
    });
    faceMesh.setOptions({
      maxNumFaces: 1,
      refineLandmarks: true,
      minDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    faceMesh.onResults(onResults);

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    videoEl.srcObject = stream;
    await videoEl.play();

    const vw = videoEl.videoWidth;
    const vh = videoEl.videoHeight;
    canvasEl.width = vw;
    canvasEl.height = vh;

    camera = new Camera(videoEl, {
      onFrame: async () => {
        await faceMesh.send({ image: videoEl });
      },
      width: vw,
      height: vh,
    });
    camera.start();
    setStatus("Running — metrics stream every 200ms");
  }

  start().catch((err) => {
    console.error(err);
    setStatus("Error: " + (err && err.message ? err.message : String(err)));
  });
})();
