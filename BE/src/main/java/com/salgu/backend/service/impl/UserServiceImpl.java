package com.salgu.backend.service.impl;

import com.salgu.backend.domain.User;
import com.salgu.backend.dto.UserResponse;
import com.salgu.backend.repository.UserRepository;
import com.salgu.backend.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {

    private final UserRepository userRepository;

    @Override
    @Transactional
    public User loginWithKakao(Long kakaoId, String nickname) {
        return userRepository.findByKakaoId(kakaoId)
                .map(user -> {
                    user.updateNickname(nickname);
                    return user;
                })
                .orElseGet(() -> userRepository.save(new User(kakaoId, nickname)));
    }

    @Override
    @Transactional(readOnly = true)
    public UserResponse getByKakaoId(Long kakaoId) {
        return userRepository.findByKakaoId(kakaoId)
                .map(UserResponse::from)
                // session exists but the member row is gone -> treat as logged out
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED));
    }
}
