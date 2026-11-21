package com.salgu.backend.service;

import com.salgu.backend.domain.User;
import com.salgu.backend.dto.UserResponse;

public interface UserService {

    /** Creates the member on first Kakao login, refreshes the nickname afterwards. */
    User loginWithKakao(Long kakaoId, String nickname);

    UserResponse getByKakaoId(Long kakaoId);
}
