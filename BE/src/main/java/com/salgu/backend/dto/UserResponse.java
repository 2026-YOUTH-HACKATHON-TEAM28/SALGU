package com.salgu.backend.dto;

import com.salgu.backend.domain.User;

public record UserResponse(Long id, String nickname) {

    public static UserResponse from(User user) {
        return new UserResponse(user.getId(), user.getNickname());
    }
}
