export const volumeVertexShader = /* glsl */ `
  out vec3 vRayOrigin;
  out vec3 vRayDirection;

  void main() {
    vec4 localCamera = inverse(modelMatrix) * vec4(cameraPosition, 1.0);
    vRayOrigin = localCamera.xyz;
    vRayDirection = position - localCamera.xyz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const volumeFragmentShader = /* glsl */ `
  precision highp float;
  precision highp sampler3D;

  uniform sampler3D uVolume;
  uniform sampler2D uTransfer;
  uniform vec3 uTextureSize;
  uniform vec3 uVoxelSpacing;
  uniform vec3 uClipMin;
  uniform vec3 uClipMax;
  uniform vec3 uLightDirection;
  uniform int uSteps;
  uniform float uDensity;
  uniform float uSurfaceEmphasis;
  uniform float uShadows;
  uniform float uAmbient;
  uniform float uDiffuse;
  uniform float uSpecular;
  uniform float uInteractive;

  in vec3 vRayOrigin;
  in vec3 vRayDirection;
  out vec4 outColor;

  const int MAX_STEPS = 768;
  const int SHADOW_STEPS = 7;

  vec2 intersectBox(vec3 origin, vec3 direction, vec3 boxMinimum, vec3 boxMaximum) {
    vec3 directionSign = mix(vec3(-1.0), vec3(1.0), step(vec3(0.0), direction));
    vec3 safeDirection = directionSign * max(abs(direction), vec3(0.000001));
    vec3 inverseDirection = 1.0 / safeDirection;
    vec3 nearPlane = (boxMinimum - origin) * inverseDirection;
    vec3 farPlane = (boxMaximum - origin) * inverseDirection;
    vec3 tMinimum = min(nearPlane, farPlane);
    vec3 tMaximum = max(nearPlane, farPlane);
    float nearDistance = max(max(tMinimum.x, tMinimum.y), tMinimum.z);
    float farDistance = min(min(tMaximum.x, tMaximum.y), tMaximum.z);
    return vec2(nearDistance, farDistance);
  }

  float random(vec2 coordinates) {
    return fract(sin(dot(coordinates, vec2(12.9898, 78.233))) * 43758.5453);
  }

  float sampleVolume(vec3 position) {
    return texture(uVolume, clamp(position, vec3(0.0), vec3(1.0))).r;
  }

  vec3 gradientAt(vec3 position) {
    vec3 texel = 1.0 / uTextureSize;
    float x = sampleVolume(position + vec3(texel.x, 0.0, 0.0)) -
      sampleVolume(position - vec3(texel.x, 0.0, 0.0));
    float y = sampleVolume(position + vec3(0.0, texel.y, 0.0)) -
      sampleVolume(position - vec3(0.0, texel.y, 0.0));
    float z = sampleVolume(position + vec3(0.0, 0.0, texel.z)) -
      sampleVolume(position - vec3(0.0, 0.0, texel.z));
    return 0.5 * vec3(x, y, z) / max(uVoxelSpacing, vec3(0.0001));
  }

  float shadowTransmittance(vec3 position, float opacityUnitMm) {
    if (uShadows < 0.5) {
      return 1.0;
    }

    vec3 physicalSize = max(uTextureSize * uVoxelSpacing, vec3(0.0001));
    float shadowStepMm = opacityUnitMm * 2.5;
    vec3 stepVector = normalize(uLightDirection) / physicalSize * shadowStepMm;
    vec3 samplePosition = position;
    float transmittance = 1.0;
    for (int index = 0; index < SHADOW_STEPS; index += 1) {
      samplePosition += stepVector;
      if (any(lessThan(samplePosition, uClipMin)) || any(greaterThan(samplePosition, uClipMax))) {
        break;
      }
      float density = sampleVolume(samplePosition);
      float baseOpacity = clamp(texture(uTransfer, vec2(density, 0.5)).a * uDensity, 0.0, 0.98);
      float opacity = 1.0 - pow(
        max(1.0 - baseOpacity, 0.0001),
        shadowStepMm / max(opacityUnitMm, 0.0001)
      );
      transmittance *= 1.0 - clamp(opacity * 0.72, 0.0, 0.9);
      if (transmittance < 0.08) {
        break;
      }
    }
    return mix(0.42, 1.0, transmittance);
  }

  void main() {
    vec3 rayDirection = normalize(vRayDirection);
    vec2 bounds = intersectBox(
      vRayOrigin,
      rayDirection,
      uClipMin - vec3(0.5),
      uClipMax - vec3(0.5)
    );
    bounds.x = max(bounds.x, 0.0);
    if (bounds.x >= bounds.y) {
      discard;
    }

    float rayLength = bounds.y - bounds.x;
    float stepLength = rayLength / float(max(uSteps, 1));
    float jitter = random(gl_FragCoord.xy);
    vec3 position = vRayOrigin + rayDirection * (bounds.x + jitter * stepLength);
    vec3 stepVector = rayDirection * stepLength;
    vec3 physicalSize = uTextureSize * uVoxelSpacing;
    vec3 physicalRayDirection = normalize(rayDirection * physicalSize);
    float physicalStepLength = length(stepVector * physicalSize);
    float opacityUnitMm = min(min(uVoxelSpacing.x, uVoxelSpacing.y), uVoxelSpacing.z);
    vec4 accumulated = vec4(0.0);

    for (int index = 0; index < MAX_STEPS; index += 1) {
      if (index >= uSteps) {
        break;
      }

      vec3 texturePosition = position + vec3(0.5);
      float scalar = sampleVolume(texturePosition);
      vec4 sampleColor = texture(uTransfer, vec2(scalar, 0.5));

      if (sampleColor.a > 0.001) {
        float gradientOpacity = 1.0;
        float lighting = 1.0;
        if (uInteractive < 0.5) {
          vec3 gradient = gradientAt(texturePosition);
          float gradientMagnitude = length(gradient);
          float surface = smoothstep(0.004, 0.12, gradientMagnitude);
          gradientOpacity = mix(1.0, mix(0.18, 1.0, surface), uSurfaceEmphasis);

          vec3 normal = gradientMagnitude > 0.0001
            ? normalize(gradient)
            : -physicalRayDirection;
          normal = faceforward(normal, physicalRayDirection, normal);
          vec3 lightDirection = normalize(uLightDirection);
          vec3 viewDirection = -physicalRayDirection;
          float lambert = max(dot(normal, lightDirection), 0.0);
          vec3 halfVector = normalize(lightDirection + viewDirection);
          float highlight = pow(max(dot(normal, halfVector), 0.0), 28.0);
          lighting = uAmbient + uDiffuse * lambert + uSpecular * highlight;
          lighting *= shadowTransmittance(texturePosition, opacityUnitMm);
        }

        float baseOpacity = clamp(sampleColor.a * uDensity * gradientOpacity, 0.0, 0.98);
        float correctedOpacity = 1.0 - pow(
          max(1.0 - baseOpacity, 0.0001),
          physicalStepLength / max(opacityUnitMm, 0.0001)
        );

        vec3 litColor = sampleColor.rgb * lighting;
        accumulated.rgb += (1.0 - accumulated.a) * litColor * correctedOpacity;
        accumulated.a += (1.0 - accumulated.a) * correctedOpacity;
        if (accumulated.a > 0.985) {
          break;
        }
      }

      position += stepVector;
    }

    if (accumulated.a < 0.002) {
      discard;
    }
    outColor = accumulated;
  }
`;
