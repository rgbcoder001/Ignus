#!/usr/bin/env bash
# Installs custom SVT-AV1 presets into HandBrake.
#
# Adds these to HandBrake's preset list:
#   - (Live) AV1 Preset
#   - (Old Live) AV1 Preset
#   - (Old Anime) AV1 Preset
#
# Audio on every preset: your original track is kept untouched, and one
# E-AC3 960 kbps 5.1 track is added next to it for compatibility.
# HandBrake reduces that track's channels and bitrate on its own when the
# source has fewer than 6 channels.
#
# Safe to run more than once: presets with these exact names are replaced,
# and any other presets you have created are left alone.
set -euo pipefail

CONFIG_DIR="$HOME/.var/app/fr.handbrake.ghb/config/ghb"
PRESETS="$CONFIG_DIR/presets.json"

if ! command -v jq >/dev/null 2>&1; then
    echo "This needs the 'jq' tool, which does not appear to be installed." >&2
    exit 1
fi

# HandBrake rewrites presets.json from memory when it exits, which would
# silently discard anything added underneath it.
if pgrep -x ghb >/dev/null 2>&1; then
    echo "HandBrake is currently running. Please close it, then try again." >&2
    exit 1
fi

NEW_PRESETS=$(cat <<'IGNIS_PRESETS_EOF'
{
  "PresetList": [
    {
      "AlignAVStart": false,
      "AudioCopyMask": [
        "copy:aac",
        "copy:ac3",
        "copy:eac3",
        "copy:truehd",
        "copy:dts",
        "copy:dtshd",
        "copy:mp3",
        "copy:opus",
        "copy:flac",
        "copy:pcm"
      ],
      "AudioEncoderFallback": "none",
      "AudioLanguageList": [
        "any"
      ],
      "AudioList": [
        {
          "AudioBitrate": 160,
          "AudioCompressionLevel": 0,
          "AudioEncoder": "copy",
          "AudioMixdown": "dpl2",
          "AudioNormalizeMixLevel": false,
          "AudioSamplerate": "48",
          "AudioTrackQualityEnable": false,
          "AudioTrackQuality": 0,
          "AudioTrackGainSlider": 0,
          "AudioTrackDRCSlider": 0
        },
        {
          "AudioBitrate": 960,
          "AudioCompressionLevel": 0,
          "AudioEncoder": "eac3",
          "AudioMixdown": "5point1",
          "AudioNormalizeMixLevel": false,
          "AudioSamplerate": "48",
          "AudioTrackQualityEnable": false,
          "AudioTrackQuality": 0,
          "AudioTrackGainSlider": 0,
          "AudioTrackDRCSlider": 0
        }
      ],
      "AudioSecondaryEncoderMode": false,
      "AudioTrackSelectionBehavior": "all",
      "AudioTrackNamePassthru": true,
      "AudioAutomaticNamingBehavior": "unnamed",
      "ChapterMarkers": true,
      "ChildrenArray": [],
      "Default": true,
      "FileFormat": "av_mkv",
      "Folder": false,
      "FolderOpen": false,
      "Optimize": false,
      "Mp4iPodCompatible": false,
      "PictureCropMode": 0,
      "PictureBottomCrop": 0,
      "PictureLeftCrop": 0,
      "PictureRightCrop": 0,
      "PictureTopCrop": 0,
      "PictureDARWidth": 3840,
      "PictureDeblockPreset": "off",
      "PictureDeblockTune": "medium",
      "PictureDeblockCustom": "strength=strong:thresh=20:blocksize=8",
      "PictureDeinterlaceFilter": "off",
      "PictureCombDetectPreset": "default",
      "PictureCombDetectCustom": "",
      "PictureDeinterlaceCustom": "",
      "PictureDenoiseCustom": "",
      "PictureDenoiseFilter": "off",
      "PictureSharpenCustom": "",
      "PictureSharpenFilter": "off",
      "PictureSharpenPreset": "medium",
      "PictureSharpenTune": "none",
      "PictureDetelecine": "off",
      "PictureDetelecineCustom": "",
      "PictureColorspacePreset": "off",
      "PictureColorspaceCustom": "",
      "PictureChromaSmoothPreset": "off",
      "PictureChromaSmoothTune": "none",
      "PictureChromaSmoothCustom": "",
      "PictureItuPAR": false,
      "PictureKeepRatio": true,
      "PicturePAR": "auto",
      "PicturePARWidth": 1,
      "PicturePARHeight": 1,
      "PictureUseMaximumSize": true,
      "PictureAllowUpscaling": false,
      "PictureForceHeight": 0,
      "PictureForceWidth": 0,
      "PicturePadMode": "none",
      "PicturePadTop": 0,
      "PicturePadBottom": 0,
      "PicturePadLeft": 0,
      "PicturePadRight": 0,
      "PicturePadColor": "black",
      "PresetName": "(Live) AV1 Preset",
      "Type": 1,
      "SubtitleAddCC": false,
      "SubtitleAddForeignAudioSearch": true,
      "SubtitleAddForeignAudioSubtitle": false,
      "SubtitleBurnBehavior": "none",
      "SubtitleBurnBDSub": false,
      "SubtitleBurnDVDSub": false,
      "SubtitleLanguageList": [
        "any"
      ],
      "SubtitleTrackSelectionBehavior": "all",
      "SubtitleTrackNamePassthru": true,
      "VideoAvgBitrate": 0,
      "VideoColorRange": "auto",
      "VideoColorMatrixCode": 0,
      "VideoEncoder": "svt_av1_10bit",
      "VideoFramerateMode": "vfr",
      "VideoGrayScale": false,
      "VideoScaler": "swscale",
      "VideoPreset": "5",
      "VideoTune": "ssim",
      "VideoProfile": "auto",
      "VideoLevel": "auto",
      "VideoOptionExtra": "enable-qm=1:qm-min=2:chroma-qm-min=8:qp-scale-compress-strength=1:variance-boost-strength=2:adaptive-film-grain=1:film-grain=4",
      "VideoQualityType": 2,
      "VideoQualitySlider": 14,
      "VideoMultiPass": true,
      "VideoTurboMultiPass": true,
      "VideoPasshtruHDRDynamicMetadata": "all",
      "x264UseAdvancedOptions": false,
      "PresetDisabled": false,
      "MetadataPassthru": true
    },
    {
      "AlignAVStart": false,
      "AudioCopyMask": [
        "copy:aac",
        "copy:ac3",
        "copy:eac3",
        "copy:truehd",
        "copy:dts",
        "copy:dtshd",
        "copy:mp3",
        "copy:opus",
        "copy:flac",
        "copy:pcm"
      ],
      "AudioEncoderFallback": "none",
      "AudioLanguageList": [
        "any"
      ],
      "AudioList": [
        {
          "AudioBitrate": 160,
          "AudioCompressionLevel": 0,
          "AudioEncoder": "copy",
          "AudioMixdown": "dpl2",
          "AudioNormalizeMixLevel": false,
          "AudioSamplerate": "48",
          "AudioTrackQualityEnable": false,
          "AudioTrackQuality": 0,
          "AudioTrackGainSlider": 0,
          "AudioTrackDRCSlider": 0
        },
        {
          "AudioBitrate": 960,
          "AudioCompressionLevel": 0,
          "AudioEncoder": "eac3",
          "AudioMixdown": "5point1",
          "AudioNormalizeMixLevel": false,
          "AudioSamplerate": "48",
          "AudioTrackQualityEnable": false,
          "AudioTrackQuality": 0,
          "AudioTrackGainSlider": 0,
          "AudioTrackDRCSlider": 0
        }
      ],
      "AudioSecondaryEncoderMode": false,
      "AudioTrackSelectionBehavior": "all",
      "AudioTrackNamePassthru": true,
      "AudioAutomaticNamingBehavior": "unnamed",
      "ChapterMarkers": true,
      "ChildrenArray": [],
      "Default": false,
      "FileFormat": "av_mkv",
      "Folder": false,
      "FolderOpen": false,
      "Optimize": false,
      "Mp4iPodCompatible": false,
      "PictureCropMode": 0,
      "PictureBottomCrop": 0,
      "PictureLeftCrop": 0,
      "PictureRightCrop": 0,
      "PictureTopCrop": 0,
      "PictureDARWidth": 3840,
      "PictureDeblockPreset": "off",
      "PictureDeblockTune": "medium",
      "PictureDeblockCustom": "strength=strong:thresh=20:blocksize=8",
      "PictureDeinterlaceFilter": "off",
      "PictureCombDetectPreset": "default",
      "PictureCombDetectCustom": "",
      "PictureDeinterlaceCustom": "",
      "PictureDenoiseCustom": "",
      "PictureDenoiseFilter": "off",
      "PictureSharpenCustom": "",
      "PictureSharpenFilter": "off",
      "PictureSharpenPreset": "medium",
      "PictureSharpenTune": "none",
      "PictureDetelecine": "off",
      "PictureDetelecineCustom": "",
      "PictureColorspacePreset": "off",
      "PictureColorspaceCustom": "",
      "PictureChromaSmoothPreset": "off",
      "PictureChromaSmoothTune": "none",
      "PictureChromaSmoothCustom": "",
      "PictureItuPAR": false,
      "PictureKeepRatio": true,
      "PicturePAR": "auto",
      "PicturePARWidth": 1,
      "PicturePARHeight": 1,
      "PictureUseMaximumSize": true,
      "PictureAllowUpscaling": false,
      "PictureForceHeight": 0,
      "PictureForceWidth": 0,
      "PicturePadMode": "none",
      "PicturePadTop": 0,
      "PicturePadBottom": 0,
      "PicturePadLeft": 0,
      "PicturePadRight": 0,
      "PicturePadColor": "black",
      "PresetName": "(Old Live) AV1 Preset",
      "Type": 1,
      "SubtitleAddCC": false,
      "SubtitleAddForeignAudioSearch": true,
      "SubtitleAddForeignAudioSubtitle": false,
      "SubtitleBurnBehavior": "none",
      "SubtitleBurnBDSub": false,
      "SubtitleBurnDVDSub": false,
      "SubtitleLanguageList": [
        "any"
      ],
      "SubtitleTrackSelectionBehavior": "all",
      "SubtitleTrackNamePassthru": true,
      "VideoAvgBitrate": 0,
      "VideoColorRange": "auto",
      "VideoColorMatrixCode": 0,
      "VideoEncoder": "svt_av1_10bit",
      "VideoFramerateMode": "vfr",
      "VideoGrayScale": false,
      "VideoScaler": "swscale",
      "VideoPreset": "5",
      "VideoTune": "ssim",
      "VideoProfile": "auto",
      "VideoLevel": "auto",
      "VideoOptionExtra": "enable-qm=1:qm-min=2:chroma-qm-min=8:qp-scale-compress-strength=1:variance-boost-strength=2:adaptive-film-grain=1:film-grain=6",
      "VideoQualityType": 2,
      "VideoQualitySlider": 14,
      "VideoMultiPass": true,
      "VideoTurboMultiPass": true,
      "VideoPasshtruHDRDynamicMetadata": "all",
      "x264UseAdvancedOptions": false,
      "PresetDisabled": false,
      "MetadataPassthru": true
    },
    {
      "AlignAVStart": false,
      "AudioCopyMask": [
        "copy:aac",
        "copy:ac3",
        "copy:eac3",
        "copy:truehd",
        "copy:mp3",
        "copy:opus",
        "copy:flac",
        "copy:pcm"
      ],
      "AudioEncoderFallback": "none",
      "AudioLanguageList": [
        "any"
      ],
      "AudioList": [
        {
          "AudioBitrate": 160,
          "AudioCompressionLevel": 0,
          "AudioEncoder": "copy",
          "AudioMixdown": "dpl2",
          "AudioNormalizeMixLevel": false,
          "AudioSamplerate": "48",
          "AudioTrackQualityEnable": false,
          "AudioTrackQuality": 0,
          "AudioTrackGainSlider": 0,
          "AudioTrackDRCSlider": 0
        },
        {
          "AudioBitrate": 960,
          "AudioCompressionLevel": 0,
          "AudioEncoder": "eac3",
          "AudioMixdown": "5point1",
          "AudioNormalizeMixLevel": false,
          "AudioSamplerate": "48",
          "AudioTrackQualityEnable": false,
          "AudioTrackQuality": 0,
          "AudioTrackGainSlider": 0,
          "AudioTrackDRCSlider": 0
        }
      ],
      "AudioSecondaryEncoderMode": false,
      "AudioTrackSelectionBehavior": "all",
      "AudioTrackNamePassthru": true,
      "AudioAutomaticNamingBehavior": "unnamed",
      "ChapterMarkers": true,
      "ChildrenArray": [],
      "Default": false,
      "FileFormat": "av_mkv",
      "Folder": false,
      "FolderOpen": false,
      "Optimize": false,
      "Mp4iPodCompatible": false,
      "PictureCropMode": 0,
      "PictureBottomCrop": 0,
      "PictureLeftCrop": 0,
      "PictureRightCrop": 0,
      "PictureTopCrop": 0,
      "PictureDARWidth": 3840,
      "PictureDeblockPreset": "off",
      "PictureDeblockTune": "medium",
      "PictureDeblockCustom": "strength=strong:thresh=20:blocksize=8",
      "PictureDeinterlaceFilter": "off",
      "PictureCombDetectPreset": "default",
      "PictureCombDetectCustom": "",
      "PictureDeinterlaceCustom": "",
      "PictureDenoiseCustom": "",
      "PictureDenoiseFilter": "off",
      "PictureSharpenCustom": "",
      "PictureSharpenFilter": "off",
      "PictureSharpenPreset": "medium",
      "PictureSharpenTune": "none",
      "PictureDetelecine": "off",
      "PictureDetelecineCustom": "",
      "PictureColorspacePreset": "off",
      "PictureColorspaceCustom": "",
      "PictureChromaSmoothPreset": "off",
      "PictureChromaSmoothTune": "none",
      "PictureChromaSmoothCustom": "",
      "PictureItuPAR": false,
      "PictureKeepRatio": true,
      "PicturePAR": "auto",
      "PicturePARWidth": 1,
      "PicturePARHeight": 1,
      "PictureUseMaximumSize": true,
      "PictureAllowUpscaling": false,
      "PictureForceHeight": 0,
      "PictureForceWidth": 0,
      "PicturePadMode": "none",
      "PicturePadTop": 0,
      "PicturePadBottom": 0,
      "PicturePadLeft": 0,
      "PicturePadRight": 0,
      "PicturePadColor": "black",
      "PresetName": "(Old Anime) AV1 Preset",
      "Type": 1,
      "SubtitleAddCC": false,
      "SubtitleAddForeignAudioSearch": true,
      "SubtitleAddForeignAudioSubtitle": false,
      "SubtitleBurnBehavior": "none",
      "SubtitleBurnBDSub": false,
      "SubtitleBurnDVDSub": false,
      "SubtitleLanguageList": [
        "any"
      ],
      "SubtitleTrackSelectionBehavior": "all",
      "SubtitleTrackNamePassthru": true,
      "VideoAvgBitrate": 0,
      "VideoColorRange": "auto",
      "VideoColorMatrixCode": 0,
      "VideoEncoder": "svt_av1_10bit",
      "VideoFramerateMode": "vfr",
      "VideoGrayScale": false,
      "VideoScaler": "swscale",
      "VideoPreset": "5",
      "VideoTune": "ssim",
      "VideoProfile": "auto",
      "VideoLevel": "auto",
      "VideoOptionExtra": "enable-qm=1:qm-min=0:chroma-qm-min=4:variance-boost-strength=3:adaptive-film-grain=1:film-grain=8",
      "VideoQualityType": 2,
      "VideoQualitySlider": 18,
      "VideoMultiPass": true,
      "VideoTurboMultiPass": true,
      "VideoPasshtruHDRDynamicMetadata": "all",
      "x264UseAdvancedOptions": false,
      "PresetDisabled": false,
      "MetadataPassthru": true
    }
  ],
  "VersionMajor": 72,
  "VersionMinor": 0,
  "VersionMicro": 0
}
IGNIS_PRESETS_EOF
)

mkdir -p "$CONFIG_DIR"

if [ -f "$PRESETS" ]; then
    echo "Merging into your existing HandBrake presets..."
    TMP=$(mktemp)
    jq --argjson new "$NEW_PRESETS" '
        ($new.PresetList | map(.PresetName)) as $names
        | .PresetList = (
            ((.PresetList // []) | map(select(.PresetName as $n | ($names | index($n)) == null)))
            + $new.PresetList
          )
    ' "$PRESETS" > "$TMP"
    mv "$TMP" "$PRESETS"
else
    echo "No HandBrake presets found yet - creating them."
    printf '%s\n' "$NEW_PRESETS" > "$PRESETS"
fi

echo
echo "Done. Open HandBrake and look under Presets > Custom:"
jq -r '.PresetList[] | "  - " + .PresetName' "$PRESETS"
