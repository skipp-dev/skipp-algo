// Single source of truth for extracting BUS input.source labels from Pine source.
//
// Both the runtime onboarding/verify parser (scripts/tv_verify_consumer_bindings.ts)
// and the build-time packager (scripts/build_tv_onboarding_package.mjs) parse the
// same .pine files: the packager bakes the labels into the portable config, the
// runtime reads them back. Keeping the regex here — importable from both a .ts and
// a plain-node .mjs — stops the two from drifting and shipping mismatched labels.
export function parseBusBindingLabels(source) {
  return [...source.matchAll(/input\.source\([^,]+,\s*(["'])(.*?)\1/g)]
    .map((match) => match[2])
    .filter((label) => label.startsWith("BUS "));
}
