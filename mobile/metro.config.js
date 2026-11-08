const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');
const config = getDefaultConfig(__dirname);
// This repo has independent app packages rather than npm workspaces.
// Watch only the shared, platform-independent API contract outside mobile/.
config.watchFolders = [...config.watchFolders, path.resolve(__dirname, '../shared')];
module.exports = config;
