package com.salgu.backend.service.impl;

import com.salgu.backend.service.UserService;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.security.oauth2.client.userinfo.DefaultOAuth2UserService;
import org.springframework.security.oauth2.client.userinfo.OAuth2UserRequest;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.stereotype.Service;

/** Called by Spring Security after Kakao returns the user info. */
@Service
@RequiredArgsConstructor
public class KakaoOAuth2UserServiceImpl extends DefaultOAuth2UserService {

    private final UserService userService;

    @Override
    public OAuth2User loadUser(OAuth2UserRequest request) {
        OAuth2User kakaoUser = super.loadUser(request);
        userService.loginWithKakao(Long.valueOf(kakaoUser.getName()), nickname(kakaoUser.getAttributes()));
        return kakaoUser;
    }

    // Kakao response: { "id": 123, "properties": { "nickname": "..." } }
    private static String nickname(Map<String, Object> attributes) {
        if (attributes.get("properties") instanceof Map<?, ?> properties
                && properties.get("nickname") instanceof String nickname) {
            return nickname;
        }
        return null;
    }
}
