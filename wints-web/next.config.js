/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    // Required for mqtt.js to work in the browser bundle
    webpack: (config, { isServer }) => {
        if (!isServer) {
            config.resolve.fallback = {
                ...config.resolve.fallback,
                net: false,
                tls: false,
                fs: false,
                path: false,
                crypto: false,
            };
        }
        return config;
    },
};

module.exports = nextConfig;
