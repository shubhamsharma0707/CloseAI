export function initBackgroundShader(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return;

    // Aetheris Ambient Grid Shader
    const vertexShaderSource = `
        attribute vec2 position;
        varying vec2 vUv;
        void main() {
            vUv = position * 0.5 + 0.5;
            gl_Position = vec4(position, 0.0, 1.0);
        }
    `;

    const fragmentShaderSource = `
        precision mediump float;
        uniform float time;
        uniform vec2 resolution;
        varying vec2 vUv;

        void main() {
            vec2 uv = gl_FragCoord.xy / resolution.xy;
            
            // Aspect ratio correction
            vec2 p = uv * 2.0 - 1.0;
            p.x *= resolution.x / resolution.y;

            // Grid
            float grid = 0.0;
            vec2 gUv = p * 4.0;
            gUv.y += time * 0.2;
            
            vec2 gridLines = fract(gUv);
            float lineThickness = 0.02;
            
            if (gridLines.x < lineThickness || gridLines.y < lineThickness) {
                grid = 0.1;
            }

            // Glows (obsidian/cyan/violet theme)
            vec3 color = vec3(0.04, 0.04, 0.04); // obsidian base
            
            // Cyan glow from left
            float cyanGlow = max(0.0, 1.0 - length(p - vec2(-1.0, 0.5)) * 0.8);
            color += vec3(0.0, 0.93, 0.98) * cyanGlow * 0.15;

            // Violet glow from right
            float violetGlow = max(0.0, 1.0 - length(p - vec2(1.0, -0.5)) * 0.8);
            color += vec3(0.47, 0.16, 1.0) * violetGlow * 0.15;

            color += vec3(0.0, 0.93, 0.98) * grid * 0.5;

            // Vignette
            float vignette = length(p);
            color -= vignette * 0.15;

            gl_FragColor = vec4(color, 1.0);
        }
    `;

    function compileShader(type, source) {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            console.error('Shader compilation error:', gl.getShaderInfoLog(shader));
            gl.deleteShader(shader);
            return null;
        }
        return shader;
    }

    const vertexShader = compileShader(gl.VERTEX_SHADER, vertexShaderSource);
    const fragmentShader = compileShader(gl.FRAGMENT_SHADER, fragmentShaderSource);

    const program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);

    gl.useProgram(program);

    const vertices = new Float32Array([
        -1.0, -1.0,
         1.0, -1.0,
        -1.0,  1.0,
        -1.0,  1.0,
         1.0, -1.0,
         1.0,  1.0
    ]);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

    const positionLoc = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    const timeLoc = gl.getUniformLocation(program, 'time');
    const resLoc = gl.getUniformLocation(program, 'resolution');

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.uniform2f(resLoc, canvas.width, canvas.height);
    }
    
    window.addEventListener('resize', resize);
    resize();

    let startTime = performance.now();
    function render(now) {
        const time = (now - startTime) / 1000.0;
        gl.uniform1f(timeLoc, time);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
        requestAnimationFrame(render);
    }

    requestAnimationFrame(render);
}
